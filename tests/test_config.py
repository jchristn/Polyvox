import sys

import pytest

from polyvox.config import Settings, boolean
from polyvox.errors import ConfigurationError


@pytest.mark.parametrize(
    "kwargs",
    [
        {"device": "imaginary"},
        {"segment_seconds": 0},
        {"retries": -1},
        {"retries": 3},
        {"max_pending": 33},
        {"gpu_device": -1},
        {"job_timeout": 0},
        {"max_duration": float("nan")},
        {"cooldown": float("inf")},
        {"max_upload_bytes": 0},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ConfigurationError):
        Settings(**kwargs)


def test_env_validation(monkeypatch):
    monkeypatch.setenv("JOB_TIMEOUT", "7200")
    monkeypatch.setenv("CPU_FALLBACK", "yes")
    assert Settings.from_env().job_timeout == 7200
    assert Settings.from_env().cpu_fallback
    monkeypatch.setenv("SEGMENT_SECONDS", "lots")
    with pytest.raises(ConfigurationError, match="SEGMENT_SECONDS"):
        Settings.from_env()


def test_boolean_rejects_typos():
    with pytest.raises(ConfigurationError):
        boolean("tru")


def test_metal_rejected_outside_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ConfigurationError, match="native macOS"):
        Settings(device="metal")


def test_missing_binary():
    with pytest.raises(ConfigurationError, match="Executable"):
        Settings(ffmpeg_bin="no-such-transcriber-executable").check()


def test_missing_model(tmp_path):
    with pytest.raises(ConfigurationError, match="model not found"):
        Settings(
            ffmpeg_bin=sys.executable,
            ffprobe_bin=sys.executable,
            model_path=str(tmp_path / "missing.bin"),
        ).check()
