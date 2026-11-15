"""Bounded admission, isolated jobs, retries, and circuit breaking."""

import json
import logging
import sys
import tempfile
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

from .config import Settings
from .errors import (
    ERROR_TYPES,
    BackendFailure,
    Busy,
    ConfigurationError,
    InvalidMedia,
    TranscriberError,
)
from .pipeline import remaining
from .process import JobCancelled, run_command

logger = logging.getLogger(__name__)


def execute_job(
    source: Path, settings: Settings, timeout: float, *, emit=None, cancel=None
) -> dict:
    if source.is_file() and source.stat().st_size > settings.max_upload_bytes:
        raise InvalidMedia("Input exceeds MAX_UPLOAD_BYTES")
    with tempfile.TemporaryDirectory(prefix="polyvox-job-", dir=settings.temp_dir) as temp:
        directory = Path(temp)
        job, result_path = directory / "job.json", directory / "result.json"
        job.write_text(
            json.dumps(
                {
                    "source": str(source.resolve()),
                    "settings": asdict(settings),
                    "stream": emit is not None,
                }
            ),
            encoding="utf-8",
        )

        def on_line(line):
            if line.startswith("POLYVOX_EVENT\t"):
                try:
                    event = json.loads(line.split("\t", 1)[1])
                except ValueError as exc:
                    raise BackendFailure("Worker returned an invalid stream event") from exc
                emit(event)

        log = run_command(
            [sys.executable, "-m", "polyvox.worker", str(job), str(result_path)],
            timeout,
            isolated=True,
            on_line=on_line if emit is not None else None,
            cancel=cancel,
        )
        try:
            response = json.loads(result_path.read_text(encoding="utf-8"))
            if "error" in response:
                logger.error("Isolated job failed: %s", log[-4000:])
                raise ERROR_TYPES.get(response["error"], BackendFailure)(response["detail"])
            return response["result"]
        except (OSError, ValueError, KeyError) as exc:
            raise BackendFailure("Worker returned no valid result") from exc


class TranscriptionService:
    def __init__(self, settings: Settings | None = None, runner=execute_job):
        settings = settings or Settings.from_env()
        self.settings = settings
        self._runner = runner
        self._slots = threading.BoundedSemaphore(1 + settings.max_pending)
        self._execution = threading.Lock()
        self._state = threading.Lock()
        self._active = False
        self._failures = 0
        self._open_until = 0.0
        self._completed = 0

    def snapshot(self) -> dict:
        with self._state:
            return {
                "active": self._active,
                "completed": self._completed,
                "consecutive_failures": self._failures,
                "circuit_open": time.monotonic() < self._open_until,
                "device": self.settings.device,
                "backend": "streaming-engine",
            }

    def check_ready(self, settings=None):
        (settings or self.settings).check()
        if self.snapshot()["circuit_open"]:
            raise Busy("Backend cooling down after repeated failures")

    def options(self, *, diarization=None, include_audio=None):
        updates = {}
        for name, value in (("diarization", diarization), ("include_audio", include_audio)):
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError(f"{name} must be a boolean")
                updates[name] = value
        return replace(self.settings, **updates)

    def stream(
        self, source, *, diarization=None, include_audio=None, request_id=None, cleanup=None
    ):
        from .events import EventStream

        return EventStream(
            self,
            Path(source),
            diarization=diarization,
            include_audio=include_audio,
            request_id=request_id,
            cleanup=cleanup,
        )

    def transcribe(
        self, source: Path, *, emit=None, cancel=None, diarization=None, include_audio=None
    ) -> dict:
        source = Path(source)
        settings = self.options(diarization=diarization, include_audio=include_audio)
        self.check_ready(settings)
        if not self._slots.acquire(blocking=False):
            raise Busy("Transcriber is at capacity; retry later")
        acquired = False
        try:
            queue_deadline = time.monotonic() + self.settings.queue_timeout
            while not acquired:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled()
                seconds = max(0, queue_deadline - time.monotonic())
                acquired = self._execution.acquire(timeout=min(seconds, 0.05))
                if not acquired and time.monotonic() >= queue_deadline:
                    break
            if not acquired:
                raise Busy("Queue wait exceeded QUEUE_TIMEOUT")
            self.check_ready(settings)
            with self._state:
                self._active = True
            try:
                result = self._attempt(source, settings=settings, emit=emit, cancel=cancel)
            except (BackendFailure, ConfigurationError):
                self._record_failure()
                raise
            except TranscriberError as exc:
                if exc.code == "timeout":
                    self._record_failure()
                raise
            else:
                with self._state:
                    self._failures = 0
                    self._open_until = 0
                    self._completed += 1
                return result
        finally:
            if acquired:
                with self._state:
                    self._active = False
                self._execution.release()
            self._slots.release()

    def _record_failure(self):
        with self._state:
            self._failures += 1
            if self._failures >= self.settings.failure_threshold:
                self._open_until = time.monotonic() + self.settings.cooldown

    def _attempt(self, source: Path, *, settings=None, emit=None, cancel=None) -> dict:
        deadline = time.monotonic() + self.settings.job_timeout
        settings = settings or self.settings
        published = False
        for attempt in range(settings.retries + 1):
            if cancel is not None and cancel.is_set():
                raise JobCancelled()
            if emit is not None:
                emit(
                    {
                        "type": "attempt",
                        "attempt": attempt + 1,
                        "reset": True,
                        "requested_device": self.settings.device,
                        "device": settings.device,
                    }
                )

            def forward(event, attempt_number=attempt + 1):
                nonlocal published
                if event.get("type") == "segment":
                    published = True
                emit({**event, "attempt": attempt_number})

            try:
                kwargs = {"emit": forward, "cancel": cancel} if emit is not None else {}
                result = self._runner(source, settings, remaining(deadline), **kwargs)
                result.setdefault("metadata", {}).update(
                    {"requested_device": self.settings.device, "attempts": attempt + 1}
                )
                return result
            except BackendFailure:
                if published or attempt == settings.retries:
                    raise
                logging.getLogger("waitress").warning("Exception encountered:", exc_info=True)
                logger.warning("Backend failed; retrying in a fresh process")
                if settings.cpu_fallback and settings.device != "cpu":
                    settings = replace(settings, device="cpu")
        raise AssertionError("unreachable")

    def clear_models(self):
        # All models leave memory on job exit; no replacement worker is started.
        if not self._execution.acquire(blocking=False):
            raise Busy("A transcription is running")
        self._execution.release()
