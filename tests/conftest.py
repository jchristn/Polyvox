from pathlib import Path

import pytest

from polyvox.config import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """No ML prerequisites needed for tests of scheduling and HTTP policy."""
    monkeypatch.setattr(Settings, "check", lambda self: None)
    return Settings(temp_dir=str(tmp_path), retries=0)


@pytest.fixture
def result():
    return {
        "segments": [
            {"start": 0.0, "end": 1.0, "len": 1.0, "speaker": "SPEAKER_00", "text": "Hello"}
        ],
        "language": "en",
        "metadata": {"device": "cpu"},
    }


@pytest.fixture
def sample():
    return Path(__file__).parent / "fixtures" / "jfk.wav"
