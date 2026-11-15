"""Exercise publishing arguments and failure propagation without contacting Docker."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Bash publishing helper runs on POSIX")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def docker_stub(tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "docker.jsonl"
    executable = directory / "docker"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['DOCKER_TEST_LOG'], 'a') as log:\n"
        "    log.write(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
        "sys.exit(int(os.environ.get('DOCKER_TEST_FAILURE', '0')) "
        "if sys.argv[2] == os.environ.get('DOCKER_TEST_FAIL_AT') else 0)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("DOCKER_TEST_LOG", str(log))
    return log


@pytest.mark.parametrize("tag", ["v1.0.0", "v1.2.3-rc1"])
def test_publishes_both_tags_and_platforms_from_any_directory(tmp_path, docker_stub, tag):
    result = subprocess.run(
        [shutil.which("bash"), str(ROOT / "build-server.sh"), tag],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in docker_stub.read_text().splitlines()]
    assert records[0]["args"] == ["buildx", "inspect", "cloud-jchristn77-jchristn77"]
    build = records[1]
    assert Path(build["cwd"]).resolve() == ROOT
    args = build["args"]
    assert args[:2] == ["buildx", "build"]
    assert args[args.index("--builder") + 1] == "cloud-jchristn77-jchristn77"
    assert args[args.index("--platform") + 1] == "linux/amd64,linux/arm64/v8"
    assert [args[i + 1] for i, arg in enumerate(args) if arg == "-t"] == [
        f"jchristn77/polyvox-server:{tag}",
        "jchristn77/polyvox-server:latest",
    ]
    assert args[args.index("--build-arg") + 1] == "API_MODE=true"
    assert args[args.index("-f") + 1] == "dockerfile-cpu"
    assert args[-2:] == ["--push", "."]


@pytest.mark.parametrize("arguments", [[], ["v1", "extra"], ["invalid/tag"], [""]])
def test_rejects_invalid_arguments_before_docker(docker_stub, arguments):
    result = subprocess.run(
        [shutil.which("bash"), str(ROOT / "build-server.sh"), *arguments], capture_output=True
    )
    assert result.returncode != 0
    assert not docker_stub.exists()


@pytest.mark.parametrize("stage", ["inspect", "build"])
def test_failure_stops_publication_and_preserves_exit_code(docker_stub, monkeypatch, stage):
    monkeypatch.setenv("DOCKER_TEST_FAIL_AT", stage)
    monkeypatch.setenv("DOCKER_TEST_FAILURE", "17")
    result = subprocess.run(
        [shutil.which("bash"), str(ROOT / "build-server.sh"), "v1.0.0"], capture_output=True
    )
    assert result.returncode == 17
    records = [json.loads(line) for line in docker_stub.read_text().splitlines()]
    assert len(records) == (1 if stage == "inspect" else 2)
