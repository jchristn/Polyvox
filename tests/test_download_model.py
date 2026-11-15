import hashlib
import io
import os
import stat

import pytest

from scripts.download_model import MODELS, download


def test_verified_model_is_readable_by_container_user(tmp_path, monkeypatch):
    content = b"public model weights"
    monkeypatch.setitem(
        MODELS,
        "nemotron-asr",
        {"sha256": hashlib.sha256(content).hexdigest(), "url": "https://example.test/model"},
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(content))
    result = download("nemotron-asr", tmp_path)
    assert result.read_bytes() == content
    if os.name != "nt":
        assert stat.S_IMODE(result.stat().st_mode) == 0o644


def test_checksum_failure_leaves_no_partial_model(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="checksum"):
        download("nemotron-asr", tmp_path)
    assert not list(tmp_path.iterdir())


def test_existing_corrupt_model_is_not_overwritten(tmp_path):
    target = tmp_path / "nemotron-asr.gguf"
    target.write_bytes(b"keep for inspection")
    with pytest.raises(ValueError, match="Existing model"):
        download("nemotron-asr", tmp_path)
    assert target.read_bytes() == b"keep for inspection"
