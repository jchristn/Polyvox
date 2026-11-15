import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from polyvox.errors import BackendFailure, Busy, InvalidMedia, JobTimeout
from polyvox.service import TranscriptionService


def test_retry_is_fresh_and_reports_cpu_fallback(settings, result):
    calls = []

    def runner(source, config, timeout):
        calls.append(config.device)
        if len(calls) == 1:
            raise BackendFailure("GPU died")
        return result

    service = TranscriptionService(
        replace(settings, device="cuda", retries=1, cpu_fallback=True), runner
    )
    response = service.transcribe(Path("audio"))
    assert calls == ["cuda", "cpu"]
    assert response["metadata"]["requested_device"] == "cuda"
    assert response["metadata"]["attempts"] == 2
    assert service.snapshot()["completed"] == 1


def test_no_implicit_cpu_fallback(settings, result):
    calls = []

    def runner(source, config, timeout):
        calls.append(config.device)
        if len(calls) == 1:
            raise BackendFailure("GPU died")
        return result

    TranscriptionService(replace(settings, device="cuda", retries=1), runner).transcribe(Path("x"))
    assert calls == ["cuda", "cuda"]


@pytest.mark.parametrize("failure", [InvalidMedia("bad input"), JobTimeout("too slow")])
def test_non_retryable_errors_and_capacity_recovery(settings, result, failure):
    calls = []

    def runner(*args):
        calls.append(1)
        if len(calls) == 1:
            raise failure
        return result

    service = TranscriptionService(replace(settings, retries=2), runner)
    with pytest.raises(type(failure)):
        service.transcribe(Path("x"))
    assert len(calls) == 1
    assert service.transcribe(Path("x"))["segments"]


def test_bounded_concurrency(settings, result):
    entered, release = threading.Event(), threading.Event()

    def runner(*args):
        entered.set()
        assert release.wait(5)
        return result

    service = TranscriptionService(settings, runner)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(service.transcribe, Path("a"))
        assert entered.wait(3)
        try:
            with pytest.raises(Busy):
                service.transcribe(Path("b"))
            with pytest.raises(Busy):
                service.clear_models()
        finally:
            release.set()
        assert first.result()["segments"]
    service.clear_models()


def test_queued_requests_survive_prior_job_completion(settings, result):
    """Queued jobs check readiness after acquiring the processing lock."""
    service = TranscriptionService(replace(settings, max_pending=8), lambda *args: result.copy())
    with ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(service.transcribe, [Path("x")] * 50))
    assert len(responses) == service.snapshot()["completed"] == 50


def test_circuit_breaks_and_recovers(settings, result, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("polyvox.service.time.monotonic", lambda: clock[0])
    broken = [True]

    def runner(*args):
        if broken[0]:
            raise BackendFailure("failed")
        return result

    service = TranscriptionService(replace(settings, failure_threshold=2), runner)
    for _ in range(2):
        with pytest.raises(BackendFailure):
            service.transcribe(Path("x"))
    with pytest.raises(Busy):
        service.transcribe(Path("x"))
    clock[0] += settings.cooldown + 1
    broken[0] = False
    assert service.transcribe(Path("x"))["segments"]
    assert service.snapshot()["consecutive_failures"] == 0


def test_retry_shares_deadline(settings, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("polyvox.service.time.monotonic", lambda: clock[0])
    calls = []

    def runner(*args):
        calls.append(1)
        clock[0] = 11
        raise BackendFailure("crash")

    service = TranscriptionService(replace(settings, job_timeout=10, retries=1), runner)
    with pytest.raises(JobTimeout):
        service.transcribe(Path("x"))
    assert len(calls) == 1
