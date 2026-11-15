"""Acceptance against actual native ASR and diarization, without gated model access."""

import base64
import io
import json
import os
import wave
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from polyvox import Engine, Settings, Transcriber
from polyvox.api import create_app
from polyvox.errors import InvalidMedia


def configured(tmp_path):
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 after installing the runtime and both models")
    settings = replace(Settings.from_env(), temp_dir=str(tmp_path), retries=0)
    settings.check()
    return settings


def validate_segments(segments, diarization, audio):
    assert segments
    text = " ".join(s["text"] for s in segments).lower()
    assert "country" in text and "ask" in text
    if diarization:
        assert any(s["speaker"].startswith("SPEAKER_") for s in segments)
    else:
        assert all(s["speaker"] == "UNKNOWN" for s in segments)
    for s in segments:
        assert s["len"] == pytest.approx(s["end"] - s["start"])
        assert ("audio" in s) is audio
        if audio:
            with wave.open(io.BytesIO(base64.b64decode(s["audio"]["data"], validate=True))) as clip:
                assert clip.getnchannels() == 1 and clip.getframerate() == 16000
                assert clip.getnframes() / 16000 == pytest.approx(s["len"], abs=0.0001)


@pytest.mark.integration
@pytest.mark.parametrize("fmt", ["json", "jsonl", "sse"])
@pytest.mark.parametrize("diarization", [False, True])
@pytest.mark.parametrize("audio", [False, True])
def test_real_primary_api_all_structured_modes(tmp_path, sample, fmt, diarization, audio):
    settings = replace(configured(tmp_path), device="cpu")
    api = create_app(settings).test_client()
    with sample.open("rb") as source:
        response = api.post(
            f"/transcribe?format={fmt}&diarization={str(diarization).lower()}&include_audio={str(audio).lower()}",
            data={"file": (source, "jfk.wav")},
        )
    assert response.status_code == 200, response.text
    spec = yaml.safe_load(Path("openapi.yaml").read_text())
    if fmt == "json":
        result = response.json
        Draft202012Validator(
            {"$ref": "#/components/schemas/Transcript", "components": spec["components"]}
        ).validate(result)
        segments = result["segments"]
    else:
        events = [
            json.loads(line[6:] if fmt == "sse" else line)
            for line in response.text.splitlines()
            if line.startswith("data: ") or (fmt == "jsonl" and line)
        ]
        assert events[-1]["type"] == "complete", events
        validator = Draft202012Validator(
            {"$ref": "#/components/schemas/StreamEvent", "components": spec["components"]}
        )
        for event in events:
            validator.validate(event)
        updates = [e for e in events if e["type"] == "segment"]
        assert [e["id"] for e in updates] == list(range(len(updates)))
        assert all(e["final"] for e in updates)
        assert events[-1]["segment_count"] == len(updates)
        segments = [e["segment"] for e in updates]
        result = events[-1]
    assert result["metadata"]["single_pass"]
    assert result["metadata"]["diarization"] is diarization
    assert result["metadata"]["include_audio"] is audio
    validate_segments(segments, diarization, audio)
    response.close()
    assert not list(tmp_path.iterdir())


@pytest.mark.integration
@pytest.mark.parametrize("diarization", [False, True])
def test_real_text_stream_and_invalid_media_recovery(tmp_path, sample, diarization):
    api = create_app(replace(configured(tmp_path), device="cpu")).test_client()
    bad = api.post("/transcribe?format=json", data={"file": (io.BytesIO(b"broken"), "bad.wav")})
    assert bad.status_code == 422
    with sample.open("rb") as source:
        response = api.post(
            "/transcribe",
            data={"file": (source, "jfk.wav"), "diarization": str(diarization).lower()},
        )
    assert response.status_code == 200
    assert "country" in response.text.lower()
    assert response.text.endswith("# complete\n")
    assert ("SPEAKER_" in response.text) if diarization else ("UNKNOWN" in response.text)
    response.close()
    assert not list(tmp_path.iterdir())


@pytest.mark.integration
def test_real_duration_limit(tmp_path, sample):
    settings = replace(configured(tmp_path), device="cpu", max_duration=1)
    with pytest.raises(InvalidMedia):
        Transcriber(settings).transcribe(sample)


@pytest.mark.integration
def test_live_library_emits_combined_segments_before_end_of_audio(tmp_path, sample):
    settings = replace(configured(tmp_path), device="cpu", diarization=True, include_audio=True)
    segments = []
    early = False
    with Engine(settings) as engine, wave.open(str(sample), "rb") as source:
        while pcm := source.readframes(2560):
            batch = engine.push_pcm16(pcm)
            if batch and source.tell() < source.getnframes():
                early = True
            segments.extend(batch)
        segments.extend(engine.finish())
    assert early, "No combined segment was available before the audio ended"
    validate_segments(segments, True, True)


@pytest.mark.hardware
def test_requested_accelerator_is_actually_used(tmp_path, sample):
    if os.environ.get("RUN_HARDWARE") != "1":
        pytest.skip("Set RUN_HARDWARE=1 with DEVICE selecting the accelerator")
    settings = replace(
        Settings.from_env(), temp_dir=str(tmp_path), retries=0, cpu_fallback=False, diarization=True
    )
    assert settings.device != "cpu"
    with Transcriber(settings).stream(sample) as stream:
        events = list(stream)
    assert events[-1]["type"] == "complete", events
    assert events[-1]["metadata"]["device"] == settings.device
    validate_segments([e["segment"] for e in events if e["type"] == "segment"], True, False)
