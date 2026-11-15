"""Decode files once, then feed the same PCM engine used by library sessions."""

import json
import math
import time
import wave
from pathlib import Path

from .config import Settings
from .engine import CHUNK_FRAMES, Engine
from .errors import BackendFailure, InvalidMedia, JobTimeout
from .process import run_command

# Exclude playlists, even when their contents are uploaded as audio.
FORMATS = "wav,mp3,flac,ogg,mov,matroska,webm,aac,asf,aiff"


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise JobTimeout("Processing deadline exceeded")
    return seconds


def decode_audio(source: Path, target: Path, settings: Settings, deadline: float):
    restrictions = ["-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS]
    try:
        raw = run_command(
            [
                settings.ffprobe_bin,
                "-v",
                "error",
                *restrictions,
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(source),
            ],
            min(30, remaining(deadline)),
        )
        duration = float(json.loads(raw).get("format", {}).get("duration", 0))
        if not math.isfinite(duration) or duration > settings.max_duration:
            raise InvalidMedia("Audio exceeds MAX_DURATION")
        run_command(
            [
                settings.ffmpeg_bin,
                "-nostdin",
                "-v",
                "error",
                "-y",
                *restrictions,
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-t",
                str(settings.max_duration + 1),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
            remaining(deadline),
        )
        with wave.open(str(target), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if seconds <= 0 or seconds > settings.max_duration:
            raise InvalidMedia("Audio is empty or exceeds MAX_DURATION")
    except (BackendFailure, ValueError, wave.Error, KeyError) as exc:
        raise InvalidMedia("Cannot decode a supported audio stream") from exc


def transcribe(source: Path, directory: Path, settings: Settings, emit=None) -> dict:
    deadline = time.monotonic() + settings.job_timeout
    audio = directory / "audio.wav"
    decode_audio(source, audio, settings, deadline)
    segments = []
    count = 0
    # Full JSON collects results; event streams retain only bounded pending words/audio.
    with Engine(settings) as engine, wave.open(str(audio), "rb") as decoded:

        def publish(batch):
            nonlocal count
            for segment in batch:
                if emit is None:
                    segments.append(segment)
                else:
                    emit({"type": "segment", "id": count, "final": True, "segment": segment})
                count += 1

        while pcm := decoded.readframes(CHUNK_FRAMES):
            remaining(deadline)
            publish(engine.push_pcm16(pcm))
        publish(engine.finish())
        remaining(deadline)
        return {
            "segments": segments,
            "segment_count": count,
            "language": engine.asr.language,
            "metadata": engine.metadata,
        }
