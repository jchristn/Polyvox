"""Real sockets verify WSGI delivery timing and disconnect propagation."""

import threading
import urllib.request

import pytest
from waitress import create_server

from polyvox.api import create_app
from polyvox.process import JobCancelled
from polyvox.service import TranscriptionService


@pytest.mark.parametrize("disconnect", [False, True])
def test_waitress_streams_before_completion_and_detects_disconnect(
    settings, result, monkeypatch, disconnect
):
    from polyvox import events as streaming

    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)
    release = threading.Event()
    stopped = threading.Event()

    def runner(source, settings, timeout, *, emit, cancel):
        try:
            emit(
                {
                    "type": "segment",
                    "id": 0,
                    "final": True,
                    "segment": result["segments"][0],
                }
            )
            while not release.wait(0.01):
                if cancel.is_set():
                    raise JobCancelled()
            return result
        finally:
            stopped.set()

    service = TranscriptionService(settings, runner)
    server = create_server(
        create_app(settings, service), host="127.0.0.1", port=0, threads=4, map={}
    )
    stop_server = threading.Event()

    def serve():
        while not stop_server.is_set():
            server.asyncore.loop(timeout=0.01, map=server._map, count=1)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        body = (
            b'--test\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
            b"\r\naudio\r\n--test--\r\n"
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.effective_port}/transcribe?format=sse",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=test"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            for line in response:
                if b'"type":"segment"' in line:
                    break
            else:
                pytest.fail("HTTP stream ended before its first segment")
            assert service.snapshot()["active"]
            assert not stopped.is_set()
            if not disconnect:
                release.set()
                assert b'"type":"complete"' in response.read()
        assert stopped.wait(3), "Disconnect did not reach the producer"
    finally:
        release.set()
        stop_server.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
        server.task_dispatcher.shutdown(timeout=2)
        server.asyncore.close_all(map=server._map)
    assert not service.snapshot()["active"]
