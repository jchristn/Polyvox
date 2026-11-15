from dataclasses import replace

import pytest

from polyvox.errors import ConfigurationError
from polyvox.providers.nemo import NemoDiarizer


class Runtime:
    def __init__(self, cadence):
        self.cadence = cadence
        self.closed = []

    def diar_create(self, config, output):
        output._obj.value = 1
        return 0

    def diar_stream_open(self, model, output):
        output._obj.value = 2
        return 0

    def diar_seconds_per_frame(self, model):
        return self.cadence

    def diar_stream_close(self, stream):
        self.closed.append("stream")

    def diar_destroy(self, model):
        self.closed.append("model")


def test_unverifiable_model_stability_rejected_and_closed(settings, monkeypatch):
    runtime = Runtime(0.08)
    monkeypatch.setattr("polyvox.providers.nemo.runtime", lambda path: runtime)
    with pytest.raises(ConfigurationError, match="V3"):
        NemoDiarizer(settings)
    assert runtime.closed == ["stream", "model"]


def test_native_holdback_cannot_bypass_segmentation_safety(settings, monkeypatch):
    runtime = Runtime(0.01)
    monkeypatch.setattr("polyvox.providers.nemo.runtime", lambda path: runtime)
    provider = NemoDiarizer(replace(settings, diarization_holdback=0))
    assert provider.holdback >= 0.511 + 0.296 + 0.229 + 0.079
    provider.close()
    assert runtime.closed == ["stream", "model"]


@pytest.mark.parametrize(
    ("platform", "ggml_name"),
    [("win32", "ggml.dll"), ("darwin", "libggml.dylib"), ("linux", "libggml.so")],
)
def test_backend_exports_loaded_from_companion_library(tmp_path, monkeypatch, platform, ggml_name):
    import types

    from polyvox.providers import nemo

    calls = []
    handle = types.SimpleNamespace(close=lambda: None)
    backend = types.SimpleNamespace(ggml_backend_load_all_from_path=lambda path: calls.append(path))
    speech = types.SimpleNamespace()
    library = tmp_path / "speech-library"
    monkeypatch.setattr(nemo.sys, "platform", platform)
    monkeypatch.setattr(nemo.os, "add_dll_directory", lambda path: handle, raising=False)
    monkeypatch.setattr(nemo, "runtime_library", lambda path: library)
    monkeypatch.setattr(nemo.abi, "bind", lambda value: value)

    def load(path):
        calls.append(path)
        return speech if path == str(library) else backend

    monkeypatch.setattr(nemo.c, "CDLL", load)
    nemo.runtime.cache_clear()
    try:
        assert nemo.runtime(str(tmp_path))._ggml is backend
        assert calls[:2] == [str(library), str(tmp_path / ggml_name)]
        if platform == "win32":
            assert speech._directory_handles == [handle]
    finally:
        nemo.runtime.cache_clear()
