import json
import threading
from http.client import HTTPConnection

import pytest

from polyvox.cli import main
from polyvox.service import TranscriptionService


def test_cli_writes_requested_files(settings, result, tmp_path, monkeypatch):
    monkeypatch.delenv("API_MODE", raising=False)
    monkeypatch.setattr(TranscriptionService, "transcribe", lambda *args: result)
    source = tmp_path / "audio.wav"
    source.write_bytes(b"audio")
    first, second = tmp_path / "out.json", tmp_path / "out.txt"
    assert (
        main(
            [
                "--input",
                str(source),
                "--output-json",
                str(first),
                "--output-txt",
                str(second),
                "--device",
                "cpu",
                "--no-diarize",
            ]
        )
        == 0
    )
    assert json.loads(first.read_text()) == result
    assert "Hello" in second.read_text()


def test_doctor_does_not_transcribe(settings, capsys):
    assert main(["--doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--input", "missing.wav", "--output-json", "x", "--output-txt", "y"],
    ],
)
def test_invalid_cli_exits_nonzero(settings, args):
    assert main(args) == 1


def test_cli_cannot_overwrite_input(settings, tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"keep")
    assert (
        main(
            [
                "--input",
                str(source),
                "--output-json",
                str(source),
                "--output-txt",
                str(tmp_path / "out"),
            ]
        )
        == 1
    )
    assert source.read_bytes() == b"keep"


def test_server_identity_on_success_application_error_and_server_rejection(settings, monkeypatch):
    from waitress import create_server

    monkeypatch.setenv("API_MODE", "true")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "0")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "128")
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("polyvox.cli.signal.signal", lambda *args: None)
    monkeypatch.setattr("polyvox.process.shutdown", lambda: None)

    def serve(app, **kwargs):
        server = create_server(app, map={}, **kwargs)
        stopped = threading.Event()

        def poll():
            while not stopped.is_set():
                server.asyncore.loop(timeout=0.01, map=server._map, count=1)

        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        try:
            for method, path, body, status in [
                ("GET", "/", None, 200),
                ("GET", "/api/v1/ws", None, 404),
                ("POST", "/transcribe", b"x" * 256, 413),
            ]:
                connection = HTTPConnection("127.0.0.1", server.effective_port, timeout=3)
                try:
                    connection.request(method, path, body=body)
                    response = connection.getresponse()
                    assert response.status == status
                    assert response.getheader("Server") == "Polyvox"
                    response.read()
                finally:
                    connection.close()
        finally:
            stopped.set()
            thread.join(timeout=2)
            server.task_dispatcher.shutdown(timeout=2)
            server.asyncore.close_all(map=server._map)
        assert not thread.is_alive()

    monkeypatch.setattr("waitress.serve", serve)
    assert main([]) == 0
