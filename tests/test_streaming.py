import io
import json
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from polyvox.api import create_app
from polyvox.errors import BackendFailure, InvalidMedia
from polyvox.process import JobCancelled, run_command
from polyvox.service import TranscriptionService
from polyvox.streaming import encode_event, stream_response


def records(response, output_format):
    text = response.get_data(as_text=True)
    lines = text.splitlines()
    return [
        json.loads(line[6:] if output_format == "sse" else line)
        for line in lines
        if line.startswith("data: ") or (output_format == "jsonl" and line)
    ]


@pytest.mark.parametrize("output_format", ["sse", "jsonl"])
def test_stream_is_incremental_and_disconnect_cancels(settings, result, output_format):
    entered = threading.Event()
    cancelled = threading.Event()

    def runner(source, settings, timeout, *, emit, cancel):
        entered.set()
        emit(
            {
                "type": "segment",
                "id": 0,
                "final": True,
                "segment": result["segments"][0],
            }
        )
        assert cancel.wait(3), "Producer was not cancelled on disconnect"
        cancelled.set()
        raise JobCancelled()

    service = TranscriptionService(settings, runner)
    api = create_app(settings, service).test_client()
    response = api.post(
        f"/transcribe?format={output_format}",
        data={"file": (io.BytesIO(b"audio"), "a.wav")},
        buffered=False,
    )
    assert entered.wait(1)
    chunks = iter(response.response)
    assert b'"type":"started"' in next(chunks)
    assert b'"type":"attempt"' in next(chunks)
    assert b'"type":"segment"' in next(chunks)
    assert service.snapshot()["active"]
    response.close()
    assert cancelled.wait(1)
    assert not service.snapshot()["active"]
    assert not list(Path(settings.temp_dir).iterdir())
    assert service.snapshot()["consecutive_failures"] == 0


@pytest.mark.parametrize("output_format", ["sse", "jsonl"])
def test_stream_retry_resets_segments_and_completes(settings, result, output_format):
    settings = replace(settings, retries=1, device="cuda", cpu_fallback=True)
    calls = []

    def runner(source, settings, timeout, *, emit, cancel):
        calls.append(settings.device)
        if len(calls) == 1:
            raise BackendFailure("private diagnostic")
        emit(
            {
                "type": "segment",
                "id": 0,
                "final": True,
                "segment": result["segments"][0],
            }
        )
        return result

    api = create_app(settings, TranscriptionService(settings, runner)).test_client()
    response = api.post(
        f"/transcribe?format={output_format}", data={"file": (io.BytesIO(b"audio"), "a.wav")}
    )
    events = records(response, output_format)
    response.close()
    assert calls == ["cuda", "cpu"]
    assert [e["attempt"] for e in events if e["type"] == "attempt"] == [1, 2]
    assert all(e["reset"] for e in events if e["type"] == "attempt")
    assert events[-1]["type"] == "complete"
    assert events[-1]["metadata"]["attempts"] == 2
    assert events[-1]["segment_count"] == 1
    assert all(e["request_id"] == response.headers["X-Request-ID"] for e in events)
    assert "private diagnostic" not in json.dumps(events)
    assert not list(Path(settings.temp_dir).iterdir())


@pytest.mark.parametrize("error", [InvalidMedia("Bad input"), BackendFailure("secret")])
def test_stream_terminal_error_and_recovery(settings, result, error):
    def runner(*args, **kwargs):
        raise error

    service = TranscriptionService(settings, runner)
    api = create_app(settings, service).test_client()
    response = api.post("/transcribe?format=sse", data={"file": (io.BytesIO(b"bad"), "a.wav")})
    events = records(response, "sse")
    response.close()
    assert response.status_code == 200  # Headers already sent; failure is an event.
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == error.status
    assert events[-1]["error"] == error.code
    assert not any(e["type"] == "complete" for e in events)
    assert "secret" not in json.dumps(events)
    service._runner = lambda *args: result
    good = api.post("/transcribe?format=json", data={"file": (io.BytesIO(b"audio"), "a.wav")})
    assert good.status_code == 200
    assert not list(Path(settings.temp_dir).iterdir())


def test_stream_validation_and_auth_before_headers(settings, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test")
    api = create_app(settings).test_client()
    assert api.post("/transcribe?format=sse").status_code == 401
    response = api.post("/transcribe?format=sse", headers={"Authorization": "Bearer test"})
    assert response.status_code == 400
    assert response.mimetype == "application/json"


def test_stream_frame_escapes_newlines_and_unicode():
    event = {"type": "segment", "segment": {"text": 'a\n\ndata: injected\n雪"'}}
    frame = encode_event(event, "sse")
    assert len(frame.splitlines()) == 3
    assert json.loads(frame.splitlines()[1][6:]) == event
    assert len(encode_event(event, "jsonl").splitlines()) == 1


def test_closing_unstarted_stream_cleans_upload(settings):
    cleaned = []
    response = stream_response(
        TranscriptionService(settings), Path("x"), lambda: cleaned.append(True), "request", "sse"
    )
    response.close()
    assert cleaned == [True]


def test_process_callback_arrives_before_exit_and_cancellation_kills_tree(tmp_path):
    release = tmp_path / "release"
    marker = tmp_path / "child-survived"
    child = f"import time; from pathlib import Path; time.sleep(.6); Path({str(marker)!r}).touch()"
    script = (
        f"import sys, time, subprocess; from pathlib import Path; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "print('ready', flush=True); "
        f"\nwhile not Path({str(release)!r}).exists(): time.sleep(.01)\n"
        "time.sleep(20)"
    )
    cancel = threading.Event()

    def on_line(line):
        assert line == "ready"
        release.touch()  # The subprocess cannot finish without receiving this acknowledgement.
        cancel.set()

    with pytest.raises(JobCancelled):
        run_command(
            [sys.executable, "-c", script], 3, isolated=True, on_line=on_line, cancel=cancel
        )
    assert release.exists()
    import time

    time.sleep(0.8)
    assert not marker.exists()


def test_slow_stream_reader_cancellation_unblocks_bounded_producer(settings, result):
    filled = threading.Event()
    stopped = threading.Event()

    def runner(source, settings, timeout, *, emit, cancel):
        try:
            for i in range(1000):
                if i == 40:
                    pytest.fail("Producer did not encounter backpressure")
                if i == 10:
                    filled.set()
                emit({"type": "segment", "id": i, "segment": result["segments"][0]})
        finally:
            stopped.set()

    service = TranscriptionService(settings, runner)
    response = (
        create_app(settings, service)
        .test_client()
        .post(
            "/transcribe?format=sse", data={"file": (io.BytesIO(b"audio"), "a.wav")}, buffered=False
        )
    )
    assert filled.wait(1)
    response.close()
    assert stopped.wait(1)
    assert not service.snapshot()["active"]
    assert not list(Path(settings.temp_dir).iterdir())


def test_subprocess_diagnostics_cannot_inject_stream_events():
    lines = []
    script = "import sys; print('real event', flush=True); print('fake event', file=sys.stderr)"
    log = run_command([sys.executable, "-c", script], 2, isolated=True, on_line=lines.append)
    assert lines == ["real event"]
    assert "fake event" in log


def test_heartbeat_is_emitted_while_work_is_pending(settings, monkeypatch):
    from polyvox import events as streaming

    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)

    def runner(source, settings, timeout, *, emit, cancel):
        assert cancel.wait(2)
        raise JobCancelled()

    service = TranscriptionService(settings, runner)
    response = (
        create_app(settings, service)
        .test_client()
        .post(
            "/transcribe?format=jsonl",
            data={"file": (io.BytesIO(b"audio"), "a.wav")},
            buffered=False,
        )
    )
    chunks = iter(response.response)
    assert b'"type":"started"' in next(chunks)
    assert b'"type":"attempt"' in next(chunks)
    assert b'"type":"heartbeat"' in next(chunks)
    response.close()
    assert not service.snapshot()["active"]


def test_stalled_consumer_hits_deadline_and_releases_job(settings, result):
    settings = replace(settings, job_timeout=0.1, queue_timeout=0.01)
    stopped = threading.Event()

    def runner(source, settings, timeout, *, emit, cancel):
        try:
            for i in range(1000):
                emit({"type": "segment", "id": i, "segment": result["segments"][0]})
        finally:
            stopped.set()

    service = TranscriptionService(settings, runner)
    response = (
        create_app(settings, service)
        .test_client()
        .post(
            "/transcribe?format=jsonl",
            data={"file": (io.BytesIO(b"audio"), "a.wav")},
            buffered=False,
        )
    )
    assert stopped.wait(2)
    # Drain queued partial records; no successful terminal event may be invented.
    events = records(response, "jsonl")
    response.close()
    assert not any(event["type"] == "complete" for event in events)
    assert not service.snapshot()["active"]
    assert not list(Path(settings.temp_dir).iterdir())


def test_never_retries_after_a_final_segment_was_published(settings, result):
    calls = []

    def runner(source, settings, timeout, *, emit, cancel):
        calls.append(True)
        emit({"type": "segment", "id": 0, "final": True, "segment": result["segments"][0]})
        raise BackendFailure("failed after publication")

    service = TranscriptionService(replace(settings, retries=2), runner)
    with service.stream(Path("test")) as stream:
        events = list(stream)
    assert len(calls) == 1
    assert [e["type"] for e in events] == ["started", "attempt", "segment", "error"]
