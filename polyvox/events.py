"""Bounded event iterator shared by the public library and HTTP output adapters."""

import contextlib
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

from .errors import BackendFailure, ConfigurationError, JobTimeout, TranscriberError
from .process import JobCancelled

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 5
BUFFER_EVENTS = 16


class EventStream:
    def __init__(
        self,
        service,
        source,
        *,
        diarization=None,
        include_audio=None,
        request_id=None,
        cleanup=None,
    ):
        self.service, self.source = service, Path(source)
        self.options = {"diarization": diarization, "include_audio": include_audio}
        service.options(**self.options)  # Validate library options before starting work.
        self.request_id = request_id or uuid.uuid4().hex
        self.cleanup = cleanup or (lambda: None)
        self.events = queue.Queue(maxsize=BUFFER_EVENTS)
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.started = False
        self.closed = False
        self.deadline = (
            time.monotonic() + service.settings.queue_timeout + service.settings.job_timeout
        )
        self.thread = threading.Thread(target=self._work, name="transcription-stream", daemon=True)
        self.iterator = self._generate()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def _emit(self, event):
        while not self.cancelled.is_set():
            try:
                self.events.put({**event, "request_id": self.request_id}, timeout=0.05)
                return
            except queue.Full:
                if time.monotonic() >= self.deadline:
                    raise JobTimeout("Stream consumer is too slow") from None
        raise JobCancelled()

    def _work(self):
        try:
            result = self.service.transcribe(
                self.source, emit=self._emit, cancel=self.cancelled, **self.options
            )
            self._emit(
                {
                    "type": "complete",
                    "segment_count": result.get("segment_count", len(result["segments"])),
                    "language": result["language"],
                    "metadata": result["metadata"],
                }
            )
        except JobCancelled:
            pass
        except Exception as exc:
            logger.warning("Stream %s failed", self.request_id, exc_info=True)
            detail = str(exc)
            if isinstance(exc, (BackendFailure, ConfigurationError)):
                detail = "Backend unavailable; inspect service logs and configuration"
            if isinstance(exc, TranscriberError):
                event = {"type": "error", "error": exc.code, "detail": detail, "status": exc.status}
                if exc.status == 503:
                    event["retry_after"] = max(1, int(self.service.settings.cooldown))
            else:
                event = {"type": "error", "error": "internal_error", "status": 500}
            with contextlib.suppress(JobCancelled, JobTimeout):
                self._emit(event)
        finally:
            try:
                self.cleanup()
            finally:
                self.finished.set()

    def _generate(self):
        try:
            if self.closed:
                return
            self.thread.start()
            self.started = True
            yield {"type": "started", "request_id": self.request_id}
            while not self.finished.is_set() or not self.events.empty():
                try:
                    event = self.events.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    if self.finished.is_set():
                        break
                    event = {"type": "heartbeat", "request_id": self.request_id}
                yield event
                if event["type"] in ("complete", "error"):
                    break
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        if self.started:
            self.thread.join(timeout=2)
        else:
            self.cleanup()
