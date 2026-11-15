import json

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
