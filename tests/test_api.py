import io
from dataclasses import replace
from pathlib import Path

import pytest

from polyvox.api import create_app
from polyvox.errors import BackendFailure, ConfigurationError, InvalidMedia, JobTimeout
from polyvox.service import TranscriptionService


def client(settings, runner):
    return create_app(settings, TranscriptionService(settings, runner)).test_client()


def test_success_text_and_json_formats(settings, result):
    seen = []

    def runner(source, *args, emit=None, **kwargs):
        seen.append(source)
        assert source.read_bytes() == b"audio"
        if emit:
            emit({"type": "segment", "id": 0, "final": True, "segment": result["segments"][0]})
        return result

    api = client(settings, runner)
    for path in ["/transcribe", "/transcribe?format=json"]:
        response = api.post(path, data={"file": (io.BytesIO(b"audio"), "../../secret.wav")})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"]
        assert response.headers["Cache-Control"] == "no-store"
        if path.endswith("json"):
            assert response.json["segments"] == result["segments"]
        else:
            assert response.text == "[0.0-1.0 SPEAKER_00] Hello\n# complete\n"
    assert all(not path.exists() for path in seen)
    assert not list(Path(settings.temp_dir).iterdir())


@pytest.mark.parametrize(
    "data", [{}, {"file": (io.BytesIO(b""), "empty.wav")}, {"file": (io.BytesIO(b"x"), "")}]
)
def test_bad_upload(settings, data):
    response = client(settings, lambda *args: None).post("/transcribe", data=data)
    assert response.status_code == 400


def test_upload_limit(settings):
    response = client(replace(settings, max_upload_bytes=100), lambda *args: None).post(
        "/transcribe", data={"file": (io.BytesIO(b"x" * 200), "x.wav")}
    )
    assert response.status_code == 413


def test_normal_file_larger_than_multipart_buffer(settings, result):
    response = client(settings, lambda *args: result).post(
        "/transcribe?format=json", data={"file": (io.BytesIO(b"x" * 700000), "audio.wav")}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "error", [BackendFailure("secret backend detail"), InvalidMedia("bad"), JobTimeout("deadline")]
)
def test_errors_cleanup_and_do_not_kill_api(settings, result, error):
    def runner(*args):
        raise error

    api = client(settings, runner)
    response = api.post("/transcribe?format=json", data={"file": (io.BytesIO(b"x"), "x.wav")})
    assert response.status_code == error.status
    assert response.json["error"] == error.code
    assert "secret" not in response.text
    assert api.get("/").status_code == 200
    assert not list(Path(settings.temp_dir).iterdir())


def test_readiness_differs_from_liveness(settings, monkeypatch):
    service = TranscriptionService(settings)

    def unavailable():
        raise ConfigurationError("missing model")

    monkeypatch.setattr(service, "check_ready", unavailable)
    api = create_app(settings, service).test_client()
    assert api.get("/").status_code == 200
    assert api.head("/").data == b""
    assert api.get("/ready").status_code == 503


def test_optional_auth(settings, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-secret")
    api = client(settings, lambda *args: None)
    assert api.get("/").status_code == 200
    assert api.get("/metrics").status_code == 401
    assert api.get("/metrics", headers={"Authorization": "Bearer väärä"}).status_code == 401
    assert api.get("/metrics", headers={"Authorization": "Bearer test-secret"}).status_code == 200


def test_clear_does_not_reload_models(settings):
    def runner(*args):
        pytest.fail("Clearing must not start inference")

    assert client(settings, runner).post("/clear-models").status_code == 200


@pytest.mark.parametrize("location", ["query", "body"])
@pytest.mark.parametrize("diarization", [False, True])
@pytest.mark.parametrize("audio", [False, True])
def test_per_request_options_do_not_mutate_service(settings, result, location, diarization, audio):
    seen = []

    def runner(source, config, timeout):
        seen.append((config.diarization, config.include_audio))
        return result

    service = TranscriptionService(settings, runner)
    api = create_app(settings, service).test_client()
    values = {
        "format": "json",
        "diarization": str(diarization).lower(),
        "include_audio": str(audio).lower(),
    }
    data = {"file": (io.BytesIO(b"audio"), "a.wav")}
    path = "/transcribe"
    if location == "query":
        from urllib.parse import urlencode

        path += "?" + urlencode(values)
    else:
        data.update(values)
    response = api.post(path, data=data)
    assert response.status_code == 200
    assert seen == [(diarization, audio)]
    assert not service.settings.diarization
    assert not service.settings.include_audio


@pytest.mark.parametrize(
    "query",
    [
        "diarization=maybe",
        "include_audio=maybe",
        "format=text&include_audio=true",
        "diarization=true&diarization=false",
        "format=xml",
    ],
)
def test_request_options_reject_ambiguity_and_invalid_values(settings, query):
    api = client(settings, lambda *args: pytest.fail("Invalid options started work"))
    response = api.post("/transcribe?" + query, data={"file": (io.BytesIO(b"x"), "a.wav")})
    assert response.status_code == 400


def test_request_options_reject_body_query_duplicate(settings):
    api = client(settings, lambda *args: pytest.fail("Ambiguous options started work"))
    response = api.post(
        "/transcribe?diarization=true",
        data={"diarization": "false", "file": (io.BytesIO(b"x"), "a.wav")},
    )
    assert response.status_code == 400
