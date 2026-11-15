import hashlib
import io
import tarfile
import zipfile

import pytest

from scripts.install_runtime import CHECKSUMS, install


def archive(monkeypatch, *, unsafe=False):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as bundle:
        info = tarfile.TarInfo("../escaped" if unsafe else "sdk/lib/runtime.so")
        content = b"test runtime"
        info.size = len(content)
        bundle.addfile(info, io.BytesIO(content))
    payload = data.getvalue()
    name = "nemo-speech-0.3.0-linux-aarch64-cpu.tar.gz"
    monkeypatch.setitem(CHECKSUMS, name, hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(payload))


def test_verified_install_is_atomic_and_repeatable(tmp_path, monkeypatch):
    archive(monkeypatch)
    target = tmp_path / "runtime"
    assert install(prefix=target, system="linux", arch="aarch64") == target
    assert (target / "lib/runtime.so").read_bytes() == b"test runtime"
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("redownload"))
    assert install(prefix=target, system="linux", arch="aarch64") == target
    assert list(tmp_path.iterdir()) == [target]


def test_corrupt_runtime_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="checksum"):
        install(prefix=tmp_path / "runtime", system="linux", arch="aarch64")
    assert not list(tmp_path.iterdir())


def test_existing_runtime_is_preserved(tmp_path):
    (tmp_path / "keep").write_text("existing")
    with pytest.raises(ValueError, match="already exists"):
        install(prefix=tmp_path, system="linux", arch="aarch64")
    assert (tmp_path / "keep").read_text() == "existing"


def test_tar_traversal_is_rejected(tmp_path, monkeypatch):
    archive(monkeypatch, unsafe=True)
    with pytest.raises(tarfile.FilterError):
        install(prefix=tmp_path / "runtime", system="linux", arch="aarch64")
    assert not list(tmp_path.iterdir())


def test_zip_traversal_is_rejected(tmp_path, monkeypatch):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("../escaped", "bad")
    payload = data.getvalue()
    monkeypatch.setitem(
        CHECKSUMS,
        "nemo-speech-0.3.0-windows-x86_64-cpu.zip",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(payload))
    with pytest.raises(ValueError, match="Unsafe"):
        install(prefix=tmp_path / "runtime", system="windows", arch="x86_64")
    assert not list(tmp_path.iterdir())


def test_unavailable_backend_is_explicit(tmp_path):
    with pytest.raises(ValueError, match="No pinned SDK"):
        install("rocm", tmp_path / "runtime", "linux", "aarch64")
    assert not list(tmp_path.iterdir())
