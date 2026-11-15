"""Bound subprocess lifetime and reap process trees on timeout/shutdown."""

import contextlib
import os
import signal
import subprocess
import tempfile
import threading
import time

from .errors import BackendFailure, JobTimeout

_lock = threading.Lock()
_children = set()
_stopping = False


def shutdown():
    global _stopping
    with _lock:
        _stopping = True
        children = list(_children)
    for process in children:
        terminate_tree(process)


def terminate_tree(process: subprocess.Popen):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait()


class JobCancelled(Exception):
    """The response consumer disconnected or stopped reading."""


def run_command(
    args: list[str], timeout: float, *, isolated=False, cwd=None, on_line=None, cancel=None
) -> str:
    """Never use a shell. Keep native-library output out of parent RAM."""
    with tempfile.TemporaryDirectory(prefix="polyvox-process-") as temp:
        path = os.path.join(temp, "output")
        with (
            open(path, "w+b") as log,
            open(path, "rb") as reader,
            tempfile.TemporaryFile() as errors,
        ):
            return _run(args, timeout, isolated, cwd, on_line, cancel, log, reader, errors)


def _run(args, timeout, isolated, cwd, on_line, cancel, log, reader, errors):
    with _lock:
        if _stopping:
            raise BackendFailure("Service is shutting down")
        process = subprocess.Popen(
            args,
            stdout=log,
            stderr=errors if on_line is not None else subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=isolated and os.name != "nt",
        )
        if isolated:
            _children.add(process)
    deadline = time.monotonic() + max(timeout, 0.01)
    pending = b""

    def drain():
        nonlocal pending
        if on_line is None:
            return
        # Bounded reads, including a native process writing an unbroken line.
        for _ in range(16):
            if cancel is not None and cancel.is_set():
                raise JobCancelled()
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(args, timeout)
            chunk = reader.read(65536)
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                on_line(line.decode("utf-8", errors="replace").rstrip("\r"))
            if len(pending) > 2 * 1024 * 1024:
                raise BackendFailure("Worker output line exceeds 2 MiB")

    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise JobCancelled()
            drain()
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                process.wait(timeout=min(seconds, 0.05))
                break
            except subprocess.TimeoutExpired:
                continue
        if on_line is not None:
            while reader.tell() < os.fstat(log.fileno()).st_size:
                drain()
            if pending:
                on_line(pending.decode("utf-8", errors="replace"))
    except BaseException as exc:
        if isolated:
            terminate_tree(process)
        else:
            process.kill()
            process.wait()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise JobTimeout("Processing deadline exceeded") from exc
        raise
    finally:
        # Reap descendants even if the wrapper crashed before its child finished.
        if isolated and os.name != "nt":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        with _lock:
            _children.discard(process)

    def capture(file, limit):
        size = os.fstat(file.fileno()).st_size
        file.seek(0)
        if size > limit:
            captured = file.read(limit // 2)
            file.seek(-limit // 2, os.SEEK_END)
            captured += b"\n...[truncated]...\n" + file.read()
        else:
            captured = file.read()
        return captured.decode("utf-8", errors="replace")

    # Only stdout is an event channel. Diagnostics cannot inject protocol records.
    output = capture(log, 32768 if on_line is not None else 65536)
    if on_line is not None:
        output += capture(errors, 32768)
    if process.returncode:
        raise BackendFailure(
            f"{os.path.basename(args[0])} exited {process.returncode}: {output[-4000:]}"
        )
    return output
