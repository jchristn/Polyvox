import io
import logging

import pytest

from polyvox.api import create_app
from polyvox.errors import BackendFailure
from polyvox.service import TranscriptionService


def access_messages(caplog):
    return [record.getMessage() for record in caplog.records if record.name == "waitress"]


def test_upload_logs_peer_url_and_body_size_without_consuming_input(settings, result, caplog):
    caplog.set_level(logging.INFO, logger="waitress")

    def runner(source, *args):
        assert source.read_bytes() == b"audio"
        return result

    app = create_app(settings, TranscriptionService(settings, runner))
    response = app.test_client().post(
        "/transcribe?format=json",
        data={"file": (io.BytesIO(b"audio"), "sample.wav")},
        environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
        headers={"X-Forwarded-For": "198.51.100.5"},
    )
    assert response.status_code == 200
    assert access_messages(caplog) == [
        "Request received from 192.0.2.10: POST http://localhost/transcribe?format=json "
        f"{response.request.content_length} bytes",
        "Response sent for 192.0.2.10: POST http://localhost/transcribe?format=json 200",
    ]


@pytest.mark.parametrize("path,status", [("/", 200), ("/metrics", 401), ("/missing", 404)])
def test_access_logs_include_health_auth_and_routing_errors(
    settings, monkeypatch, caplog, path, status
):
    monkeypatch.setenv("API_TOKEN", "secret")
    caplog.set_level(logging.INFO, logger="waitress")
    headers = {"Authorization": "Bearer secret"} if status == 404 else {}
    response = create_app(settings).test_client().get(path, headers=headers)
    assert response.status_code == status
    messages = access_messages(caplog)
    assert messages[0] == f"Request received from 127.0.0.1: GET http://localhost{path} 0 bytes"
    assert messages[-1] == f"Response sent for 127.0.0.1: GET http://localhost{path} {status}"


@pytest.mark.parametrize("output_format", ["json", "sse", "jsonl", "text"])
@pytest.mark.parametrize("error_type,status", [(BackendFailure, 503), (ValueError, 500)])
def test_exception_logs_preserve_traceback_and_cause(
    settings, caplog, output_format, error_type, status
):
    caplog.set_level(logging.INFO, logger="waitress")

    def runner(*args, **kwargs):
        try:
            raise RuntimeError("private original cause")
        except RuntimeError as exc:
            raise error_type("private backend failure") from exc

    app = create_app(settings, TranscriptionService(settings, runner))
    response = app.test_client().post(
        f"/transcribe?format={output_format}",
        data={"file": (io.BytesIO(b"audio"), "sample.wav")},
        buffered=True,
    )
    response.close()
    assert response.status_code == (status if output_format == "json" else 200)
    assert b"private" not in response.data
    exceptions = [r for r in caplog.records if r.getMessage() == "Exception encountered:"]
    assert len(exceptions) == 1
    record = exceptions[0]
    assert record.name == "waitress" and record.levelno == logging.WARNING
    formatted = logging.Formatter("%(message)s").format(record)
    assert formatted.startswith("Exception encountered:\nTraceback (most recent call last):")
    assert "RuntimeError: private original cause" in formatted
    assert f"{error_type.__name__}: private backend failure" in formatted
    assert "direct cause" in formatted
    assert len([m for m in access_messages(caplog) if m.startswith("Response sent for")]) == 1


def test_unknown_streamed_request_size_does_not_read_body(settings, caplog):
    caplog.set_level(logging.INFO, logger="waitress")

    class UnreadableBody:
        def read(self, *args):
            pytest.fail("Access logging must not read the request body")

    response = (
        create_app(settings)
        .test_client()
        .post(
            "/clear-models",
            environ_overrides={"wsgi.input_terminated": True, "wsgi.input": UnreadableBody()},
        )
    )
    assert response.status_code == 200
    assert access_messages(caplog)[0].endswith("unknown bytes")


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/api/v1/ws", 404),
        ("POST", "/api/v1/auth/refresh", 404),
        ("GET", "/api/v1/notifications/unread-count", 404),
        ("GET", "/api/v1/me/messaging/unread-count", 404),
        ("GET", "/transcribe", 405),
        ("POST", "/transcribe?format=xml", 400),
    ],
)
def test_expected_http_errors_keep_access_logs_without_tracebacks(
    settings, caplog, method, path, status
):
    caplog.set_level(logging.INFO, logger="waitress")
    response = create_app(settings).test_client().open(path, method=method)
    assert response.status_code == status
    assert response.json["error"]
    assert len(access_messages(caplog)) == 2
    assert access_messages(caplog)[-1].endswith(f" {status}")
    assert all(record.exc_info is None for record in caplog.records)
