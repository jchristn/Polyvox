"""One-pass, model-independent PCM engine shared by files and live library sessions."""

import base64
import io
import math
import sys
import tempfile
import time
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

from .config import Settings
from .errors import BackendFailure, InvalidMedia, JobTimeout
from .providers import create_provider

SAMPLE_RATE = 16000
CHUNK_FRAMES = 2560


class Engine:
    """Push mono 16 kHz PCM16 chunks; receive finalized, append-only segments.

    Owns one resident recognizer and optional diarizer. Use as a context manager.
    Provider factories are injectable for embedded applications and testing.
    Hard cancellation of native calls is supplied by the isolated service worker.
    """

    def __init__(self, settings=None, *, asr_factory=None, diarizer_factory=None):
        self.settings = settings or Settings()
        self._resources = ExitStack()
        self._closed = False
        self._finished = False
        self._deadline = time.monotonic() + self.settings.job_timeout
        self.frames = 0
        self.segment_count = 0
        self.audio_bytes = 0
        self.pending = []
        self._last_word_end = 0.0
        try:
            self.asr = (asr_factory or (lambda s: create_provider("asr", s)))(self.settings)
            self._resources.callback(self.asr.close)
            self.diarizer = None
            if self.settings.diarization:
                self.diarizer = (diarizer_factory or (lambda s: create_provider("diarization", s)))(
                    self.settings
                )
                self._resources.callback(self.diarizer.close)
            self.pool = self._resources.enter_context(ThreadPoolExecutor(max_workers=2))
            self.audio = (
                self._resources.enter_context(tempfile.TemporaryFile())  # noqa: SIM115
                if self.settings.include_audio
                else None
            )
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self._closed:
            self._closed = True
            self._resources.close()

    def _check(self):
        if self._closed or self._finished:
            raise ValueError("Session is closed or finished")
        if time.monotonic() >= self._deadline:
            raise JobTimeout("Processing deadline exceeded")

    def _queue(self, words):
        if not words:
            return
        for word in words:
            if not (
                math.isfinite(word.start)
                and math.isfinite(word.end)
                and 0 <= word.start <= word.end <= self.frames / SAMPLE_RATE + 0.1
                and word.start >= self._last_word_end - 0.001
            ):
                raise BackendFailure("ASR provider returned invalid or repeated word timestamps")
            self._last_word_end = word.end
        self.pending.append(words)

    def push_pcm16(self, pcm: bytes) -> list[dict]:
        """Accept at most one second of PCM16 LE; timestamps use a session clock."""
        self._check()
        if len(pcm) % 2 or len(pcm) > SAMPLE_RATE * 2:
            raise ValueError("Provide complete PCM16 samples in chunks of at most one second")
        if not pcm:
            return []
        self.frames += len(pcm) // 2
        if self.frames > self.settings.max_duration * SAMPLE_RATE:
            raise InvalidMedia("Audio exceeds MAX_DURATION")
        if self.audio is not None:
            self.audio.seek(0, 2)
            self.audio.write(pcm)
        values = array("h", pcm)
        if sys.byteorder != "little":
            values.byteswap()
        samples = array("f", (value / 32768 for value in values))
        recognition = self.pool.submit(self.asr.push, samples)
        diarization = self.pool.submit(self.diarizer.push, samples) if self.diarizer else None
        try:
            words = recognition.result()
        finally:
            if diarization:
                diarization.result()
        self._queue(words)
        self._check()
        return self._ready()

    def finish(self) -> list[dict]:
        self._check()
        recognition = self.pool.submit(self.asr.finish)
        diarization = self.pool.submit(self.diarizer.finish) if self.diarizer else None
        try:
            words = recognition.result()
        finally:
            if diarization:
                diarization.result()
        self._queue(words)
        self._check()
        self._finished = True
        return self._ready(flush=True)

    def _ready(self, flush=False):
        ready = []
        cutoff = self.diarizer.stable_until if self.diarizer else math.inf
        if not self.pending or (not flush and self.pending[0][-1].end > cutoff):
            return ready
        turns = self.diarizer.turns() if self.diarizer else []
        while self.pending and (flush or self.pending[0][-1].end <= cutoff):
            words = self.pending.pop(0)
            group, speaker = [], None
            for word in words:
                scores = {}
                for turn in turns:
                    overlap = max(0, min(word.end, turn.end) - max(word.start, turn.start))
                    scores[turn.speaker] = scores.get(turn.speaker, 0) + overlap
                label = (
                    max(scores, key=scores.get)
                    if scores and max(scores.values()) > 0
                    else "UNKNOWN"
                )
                if group and (
                    label != speaker
                    or word.start - group[-1].end > 0.8
                    or word.end - group[0].start > self.settings.segment_seconds
                ):
                    ready.append(self._segment(group, speaker))
                    group = []
                group.append(word)
                speaker = label
            if group:
                ready.append(self._segment(group, speaker))
        return ready

    def _segment(self, words, speaker):
        start = round(words[0].start, 3)
        end = round(min(words[-1].end, self.frames / SAMPLE_RATE), 3)
        segment = {
            "start": start,
            "end": end,
            "len": round(end - start, 3),
            "text": " ".join(word.text for word in words).strip(),
            "speaker": speaker,
        }
        if self.audio is not None:
            first = round(start * SAMPLE_RATE)
            last = round(end * SAMPLE_RATE)
            self.audio.seek(first * 2)
            pcm = self.audio.read((last - first) * 2)
            clip = io.BytesIO()
            with wave.open(clip, "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(SAMPLE_RATE)
                target.writeframes(pcm)
            data = base64.b64encode(clip.getvalue()).decode("ascii")
            self.audio_bytes += len(data)
            if self.audio_bytes > self.settings.max_audio_bytes:
                raise InvalidMedia(
                    "Audio output exceeds MAX_AUDIO_BYTES; disable include_audio or split input"
                )
            segment["audio"] = {
                "encoding": "base64",
                "content_type": "audio/wav",
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "data": data,
            }
        self.segment_count += 1
        return segment

    @property
    def metadata(self):
        return {
            "backend": "streaming-engine",
            "asr_provider": self.settings.asr_provider,
            "diarization_provider": self.settings.diarization_provider if self.diarizer else None,
            "asr_model": self.settings.model_path,
            "diarization_model": self.settings.diarization_model if self.diarizer else None,
            "device": self.asr.device,
            "diarization_device": self.diarizer.device if self.diarizer else None,
            "diarization": self.diarizer is not None,
            "include_audio": self.settings.include_audio,
            "alignment": "word-timestamps",
            "single_pass": True,
        }
