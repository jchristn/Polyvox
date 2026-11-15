import os
import sys
import time

import pytest

from polyvox.errors import BackendFailure, JobTimeout
from polyvox.process import run_command


def test_real_process_failure_and_next_success():
    with pytest.raises(BackendFailure, match="exited 7"):
        run_command([sys.executable, "-c", "raise SystemExit(7)"], 5, isolated=True)
    assert (
        run_command([sys.executable, "-c", 'print("healthy")'], 5, isolated=True).strip()
        == "healthy"
    )


def test_process_output_bounded():
    output = run_command([sys.executable, "-c", 'print("x" * 200000)'], 5, isolated=True)
    assert len(output) < 65600


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group crash cleanup")
def test_crashed_wrapper_does_not_leave_child(tmp_path):
    marker = tmp_path / "orphan"
    child = f"import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).touch()"
    parent = (
        f'import subprocess,sys; subprocess.Popen([sys.executable,"-c",{child!r}]);'
        "raise SystemExit(7)"
    )
    with pytest.raises(BackendFailure):
        run_command([sys.executable, "-c", parent], 5, isolated=True)
    time.sleep(0.7)
    assert not marker.exists()


def test_timeout_kills_child_tree(tmp_path):
    marker = tmp_path / "survived"
    child = f"import time; from pathlib import Path; time.sleep(1.5); Path({str(marker)!r}).touch()"
    parent = (
        f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]);'
        "time.sleep(20)"
    )
    start = time.monotonic()
    with pytest.raises(JobTimeout):
        run_command([sys.executable, "-c", parent], 0.5, isolated=True)
    assert time.monotonic() - start < 5
    time.sleep(1.5)
    assert not marker.exists()


def test_arguments_not_interpreted_by_shell(tmp_path):
    literal = "$(touch SHOULD_NOT_EXIST); & echo unsafe"
    output = run_command([sys.executable, "-c", "import sys; print(sys.argv[1])", literal], 5)
    assert output.strip() == literal
