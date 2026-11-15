import sys
from pathlib import Path

import pytest

from polyvox.config import Settings
from polyvox.errors import InvalidMedia
from polyvox.service import execute_job


def test_real_isolated_worker_error_and_cleanup(tmp_path):
    # Python rejects ffprobe's arguments, simulating a decoder error in a real child process.
    settings = Settings(ffprobe_bin=sys.executable, temp_dir=str(tmp_path))
    with pytest.raises(InvalidMedia):
        execute_job(Path("bad-input"), settings, 5)
    assert not list(tmp_path.iterdir())
