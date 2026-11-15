"""Validated configuration shared by CLI and API, with no ML imports."""

import math
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError

DEVICES = ("cpu", "cuda", "metal", "rocm", "vulkan", "qualcomm")


def boolean(value: str) -> bool:
    if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
        raise ConfigurationError(f"Invalid boolean: {value!r}")
    return value.lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class Settings:
    device: str = "cpu"
    model_path: str = "models/nemotron-asr.gguf"
    runtime_dir: str = ".runtime/nemo"
    asr_provider: str = "nemo"
    diarization_provider: str = "nemo"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    language: str = "auto"
    gpu_device: int = 0
    diarization: bool = False
    diarization_model: str = "models/nemotron-diar.gguf"
    diarization_device: str = "cpu"
    include_audio: bool = False
    segment_seconds: float = 8
    diarization_holdback: float = 1.2
    max_audio_bytes: int = 64 * 1024 * 1024
    job_timeout: float = 3600
    max_duration: float = 7200
    max_upload_bytes: int = 512 * 1024 * 1024
    max_pending: int = 0
    queue_timeout: float = 5
    retries: int = 1
    cpu_fallback: bool = False
    failure_threshold: int = 3
    cooldown: float = 30
    temp_dir: str | None = None

    def __post_init__(self):
        if self.device not in DEVICES:
            raise ConfigurationError(f"DEVICE must be one of {', '.join(DEVICES)}")
        if self.device == "metal" and sys.platform != "darwin":
            raise ConfigurationError("Metal requires native macOS; Linux containers cannot use it")
        for name in ("max_upload_bytes", "failure_threshold", "max_audio_bytes"):
            if getattr(self, name) < 1:
                raise ConfigurationError(f"{name} must be positive")
        for name in ("gpu_device", "max_pending", "retries"):
            if getattr(self, name) < 0:
                raise ConfigurationError(f"{name} must be non-negative")
        if self.retries > 2 or self.max_pending > 32:
            raise ConfigurationError("retries must be <= 2 and max_pending <= 32")
        for name in ("job_timeout", "max_duration", "queue_timeout", "cooldown", "segment_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f"{name} must be finite and positive")

        if not 0 <= self.diarization_holdback <= 10:
            raise ConfigurationError("diarization_holdback must be between 0 and 10 seconds")
        if not 1 <= self.segment_seconds <= 30:
            raise ConfigurationError("segment_seconds must be between 1 and 30 seconds")
        if self.diarization_device not in DEVICES:
            raise ConfigurationError("Invalid diarization_device")
        for provider in (self.asr_provider, self.diarization_provider):
            if provider != "nemo" and ":" not in provider:
                raise ConfigurationError("Provider must be nemo or an installed module:factory")

    @classmethod
    def from_env(cls):
        defaults = cls()
        names = {
            "device": "DEVICE",
            "model_path": "MODEL_PATH",
            "runtime_dir": "NEMO_RUNTIME_DIR",
            "asr_provider": "ASR_PROVIDER",
            "diarization_provider": "DIARIZATION_PROVIDER",
            "include_audio": "INCLUDE_AUDIO",
            "segment_seconds": "SEGMENT_SECONDS",
            "diarization_holdback": "DIARIZATION_HOLDBACK",
            "max_audio_bytes": "MAX_AUDIO_BYTES",
            "diarization_device": "DIARIZATION_DEVICE",
            "ffmpeg_bin": "FFMPEG_BIN",
            "ffprobe_bin": "FFPROBE_BIN",
            "language": "LANGUAGE",
            "gpu_device": "GPU_DEVICE",
            "diarization": "DIARIZATION",
            "diarization_model": "DIARIZATION_MODEL",
            "job_timeout": "JOB_TIMEOUT",
            "max_duration": "MAX_DURATION",
            "max_upload_bytes": "MAX_UPLOAD_BYTES",
            "max_pending": "MAX_PENDING",
            "queue_timeout": "QUEUE_TIMEOUT",
            "retries": "JOB_RETRIES",
            "cpu_fallback": "CPU_FALLBACK",
            "failure_threshold": "FAILURE_THRESHOLD",
            "cooldown": "FAILURE_COOLDOWN",
            "temp_dir": "TEMP_DIR",
        }
        values = {}
        for field, env in names.items():
            if env not in os.environ:
                continue
            default = getattr(defaults, field)
            convert = boolean if isinstance(default, bool) else type(default)
            try:
                values[field] = os.environ[env] if default is None else convert(os.environ[env])
            except (ValueError, TypeError) as exc:
                raise ConfigurationError(f"Invalid {env}") from exc
        return cls(**values)

    def check(self):
        """Check prerequisites without downloading models or initializing a GPU."""
        for program in (self.ffmpeg_bin, self.ffprobe_bin):
            if not shutil.which(program):
                raise ConfigurationError(f"Executable not found: {program}")
        if self.asr_provider == "nemo":
            if not Path(self.model_path).is_file():
                raise ConfigurationError(f"ASR model not found: {self.model_path}")
            runtime_library(self.runtime_dir)
        if self.diarization and self.diarization_provider == "nemo":
            if not Path(self.diarization_model).is_file():
                raise ConfigurationError(f"Diarization model not found: {self.diarization_model}")
            runtime_library(self.runtime_dir)
        if self.temp_dir:
            Path(self.temp_dir).mkdir(parents=True, exist_ok=True)


def runtime_library(directory: str) -> Path:
    root = Path(directory).resolve()
    if sys.platform == "win32":
        candidates = [root / "bin/nemo_speech_asr_c.dll", root / "bin/libnemo_speech_asr_c.dll"]
    elif sys.platform == "darwin":
        candidates = [root / "lib/libnemo_speech_asr_c.dylib"]
    else:
        candidates = [root / "lib/libnemo_speech_asr_c.so", root / "lib64/libnemo_speech_asr_c.so"]
    for path in candidates:
        if path.is_file():
            return path
    raise ConfigurationError(
        f"NeMo-Speech C runtime not found in {root}; run scripts/install_runtime.py"
    )
