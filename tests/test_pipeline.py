import io
import wave
from array import array
from dataclasses import replace

import pytest

from polyvox.engine import Engine
from polyvox.errors import BackendFailure, InvalidMedia
from polyvox.providers import Turn, Word, create_provider


class ASR:
    device = "cpu"
    language = "en"

    def __init__(self, settings):
        self.position = 0
        self.closed = False

    def push(self, samples):
        start = self.position
        self.position += len(samples) / 16000
        return [
            Word(start, self.position / 2 + start / 2, "Hello"),
            Word(self.position / 2 + start / 2, self.position, "world"),
        ]

    def finish(self):
        return []

    def close(self):
        self.closed = True


class Diarizer:
    device = "cpu"

    def __init__(self, settings):
        self.stable_until = 0
        self.closed = False

    def push(self, samples):
        self.stable_until += len(samples) / 16000

    def finish(self):
        self.stable_until = float("inf")

    def turns(self):
        return [Turn(0, 0.5, "SPEAKER_00"), Turn(0.5, 5, "SPEAKER_01")]

    def close(self):
        self.closed = True


@pytest.mark.parametrize("diarization", [False, True])
@pytest.mark.parametrize("audio", [False, True])
def test_engine_single_pass_labels_and_exact_audio(settings, diarization, audio):
    import base64

    pcm = array("h", [123] * 16000).tobytes()
    settings = replace(settings, diarization=diarization, include_audio=audio)
    with Engine(settings, asr_factory=ASR, diarizer_factory=Diarizer) as engine:
        segments = engine.push_pcm16(pcm)
        segments += engine.finish()
        assert engine.segment_count == len(segments)
        assert engine.asr.position == 1
        assert len(segments) == (2 if diarization else 1)
        assert [s["speaker"] for s in segments] == (
            ["SPEAKER_00", "SPEAKER_01"] if diarization else ["UNKNOWN"]
        )
        for segment in segments:
            assert segment["len"] == segment["end"] - segment["start"]
            assert ("audio" in segment) is audio
            if audio:
                raw = base64.b64decode(segment["audio"]["data"], validate=True)
                with wave.open(io.BytesIO(raw), "rb") as clip:
                    assert clip.getframerate() == 16000
                    assert clip.getnchannels() == 1
                    assert clip.getnframes() == round(segment["len"] * 16000)
                    assert (
                        clip.readframes(clip.getnframes()) == pcm[: round(segment["len"] * 32000)]
                    )
    assert engine.asr.closed
    if diarization:
        assert engine.diarizer.closed


def test_waits_for_diarization_watermark_and_emits_once(settings):
    class Delayed(Diarizer):
        def push(self, samples):
            pass

    with Engine(
        replace(settings, diarization=True), asr_factory=ASR, diarizer_factory=Delayed
    ) as engine:
        assert engine.push_pcm16(b"\0\0" * 16000) == []
        assert engine.segment_count == 0
        assert len(engine.finish()) == 2
        with pytest.raises(ValueError):
            engine.finish()


def test_providers_are_independent_and_run_concurrently(settings):
    import threading

    entered_asr, entered_diar = threading.Event(), threading.Event()

    class ConcurrentASR(ASR):
        def push(self, samples):
            entered_asr.set()
            assert entered_diar.wait(2)
            return super().push(samples)

    class ConcurrentDiarizer(Diarizer):
        def push(self, samples):
            entered_diar.set()
            assert entered_asr.wait(2)
            super().push(samples)

    with Engine(
        replace(settings, diarization=True),
        asr_factory=ConcurrentASR,
        diarizer_factory=ConcurrentDiarizer,
    ) as engine:
        assert engine.push_pcm16(b"\0\0" * 16000)


def test_audio_budget_and_duration_limit_release_providers(settings):
    for options in ({"max_audio_bytes": 1, "include_audio": True}, {"max_duration": 0.5}):
        with (
            pytest.raises(InvalidMedia),
            Engine(replace(settings, **options), asr_factory=ASR) as engine,
        ):
            engine.push_pcm16(b"\0\0" * 16000)
        assert engine.asr.closed


@pytest.mark.parametrize(
    "word", [Word(1, 0, "bad"), Word(0, float("nan"), "bad"), Word(0, 10, "bad")]
)
def test_invalid_provider_timestamps_fail(settings, word):
    class Broken(ASR):
        def push(self, samples):
            return [word]

    with Engine(settings, asr_factory=Broken) as engine, pytest.raises(BackendFailure):
        engine.push_pcm16(b"\0\0" * 16000)


def test_models_and_provider_factories_can_be_swapped(settings, monkeypatch):
    import sys
    import types

    seen = []

    def factory(config):
        seen.append(config.model_path)
        return ASR(config)

    monkeypatch.setitem(sys.modules, "custom_asr", types.SimpleNamespace(create=factory))
    first = create_provider(
        "asr", replace(settings, asr_provider="custom_asr:create", model_path="model-a")
    )
    second = create_provider(
        "asr", replace(settings, asr_provider="custom_asr:create", model_path="model-b")
    )
    assert seen == ["model-a", "model-b"]
    first.close()
    second.close()


def test_diarizer_can_be_replaced_independently(settings, monkeypatch):
    import sys
    import types

    seen = []

    def factory(config):
        seen.append(config.diarization_model)
        return Diarizer(config)

    monkeypatch.setitem(sys.modules, "custom_diar", types.SimpleNamespace(create=factory))
    config = replace(
        settings,
        diarization=True,
        diarization_provider="custom_diar:create",
        diarization_model="speaker-model-b",
    )
    with Engine(config, asr_factory=ASR) as engine:
        segments = engine.push_pcm16(b"\0\0" * 16000)
        assert segments[-1]["speaker"] == "SPEAKER_01"
        assert engine.metadata["diarization_provider"] == "custom_diar:create"
    assert seen == ["speaker-model-b"]
    assert engine.diarizer.closed and engine.asr.closed
