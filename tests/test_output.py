import json

import pytest

from polyvox.output import write_output


def test_atomic_outputs_unicode_and_directories(tmp_path, result):
    result["segments"][0]["text"] = "こんにちは"
    first, second = tmp_path / "new" / "out.json", tmp_path / "other" / "out.txt"
    write_output(result, str(first), str(second))
    assert json.loads(first.read_text(encoding="utf-8")) == result
    assert "こんにちは" in second.read_text(encoding="utf-8")


def test_reject_identical_output_paths(tmp_path, result):
    with pytest.raises(ValueError):
        write_output(result, str(tmp_path / "same"), str(tmp_path / "same"))


def test_staging_failure_keeps_existing_output(tmp_path, result, monkeypatch):
    target = tmp_path / "out.json"
    target.write_text("original")
    import polyvox.output as output

    original = output.tempfile.NamedTemporaryFile
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return original(*args, **kwargs)

    monkeypatch.setattr(output.tempfile, "NamedTemporaryFile", fail_second)
    with pytest.raises(OSError):
        write_output(result, str(target), str(tmp_path / "out.txt"))
    assert target.read_text() == "original"
    assert list(tmp_path.iterdir()) == [target]
