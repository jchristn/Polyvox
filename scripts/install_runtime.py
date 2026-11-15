#!/usr/bin/env python3
"""Install a checksum-pinned NeMo-Speech.cpp SDK. No models are downloaded."""

import argparse
import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.3.0"
CHECKSUMS = dict(
    [
        (
            "nemo-speech-0.3.0-linux-aarch64-cpu.tar.gz",
            "56858eaf50d19b05902c043f65d0057352bdc107ae380c41053bfbddfc204bf1",
        ),
        (
            "nemo-speech-0.3.0-linux-aarch64-cuda12.tar.gz",
            "8bc2b18589f6493373af1163ecd937cc6eba91b0305c585c6b898cd3b8a47028",
        ),
        (
            "nemo-speech-0.3.0-linux-aarch64-cuda13.tar.gz",
            "5d8e55d5d14902a5845fb5129478446db5578fd470a80e3b621da001d7f0a971",
        ),
        (
            "nemo-speech-0.3.0-linux-aarch64-vulkan.tar.gz",
            "0de233655dd579117f8f0cfd6c9dc77fe53bf11673cc44b5c42017a1fb2b8140",
        ),
        (
            "nemo-speech-0.3.0-linux-x86_64-cpu.tar.gz",
            "255f12b722ab15b2a38a51cf125d56e3fa97058b528f7e895b39d6a473deb06e",
        ),
        (
            "nemo-speech-0.3.0-linux-x86_64-cuda.tar.gz",
            "eca00a1f67d3ca200ddba11dd71c4f3d67e044cc0939d17d073978e40b995917",
        ),
        (
            "nemo-speech-0.3.0-linux-x86_64-vulkan.tar.gz",
            "2a8b2ca4610b6ea5d659ba10794526f6e5a77fb1623d52c35272a9fd1f74abac",
        ),
        (
            "nemo-speech-0.3.0-macos-aarch64-cpu.tar.gz",
            "2c3a7a719b778daeb14f147e011891f16e4b2ac62388d8b8d8b365cc2eebdf15",
        ),
        (
            "nemo-speech-0.3.0-macos-aarch64-metal.tar.gz",
            "2b972ed8b5dba07492212acf8cb75cbf34ecb141198ffa1997febe84b7c4d9ed",
        ),
        (
            "nemo-speech-0.3.0-macos-x86_64-cpu.tar.gz",
            "97e98aa5eb82dffa4f513f26336b5301d792c9fb43f720ac8f9520a0e92ffe3f",
        ),
        (
            "nemo-speech-0.3.0-windows-aarch64-cuda.zip",
            "69df7a29636ebf8fdaa20e7a2a6bd03c2838c69dc751fd00af62f0d7f041282a",
        ),
        (
            "nemo-speech-0.3.0-windows-x86_64-cpu.zip",
            "4ed9740e361e4653f56c3dce7d1e81883a1c8b831c1bd7d01567fff1130b5b05",
        ),
        (
            "nemo-speech-0.3.0-windows-x86_64-cuda.zip",
            "d0d32ae1bf6ee0534767a47b2aa0e9e2ff6fe39643465c0baae9301d04f6ed42",
        ),
        (
            "nemo-speech-0.3.0-windows-x86_64-vulkan.zip",
            "72b3b8b41bfe2be0320eff4e9d310594e4f99deefcde4a157799a039656963ce",
        ),
    ]
)


def install(device="cpu", prefix=Path(".runtime/nemo"), system=None, arch=None):
    system = system or {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(
        platform.system()
    )
    arch = arch or {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "AMD64": "x86_64",
        "x86_64": "x86_64",
    }.get(platform.machine())
    backend = "vulkan" if device == "qualcomm" else device
    if system == "linux" and arch == "aarch64" and backend == "cuda":
        backend = "cuda13"
    extension = "zip" if system == "windows" else "tar.gz"
    name = f"nemo-speech-{VERSION}-{system}-{arch}-{backend}.{extension}"
    if name not in CHECKSUMS:
        raise ValueError(
            f"No pinned SDK for {system}/{arch}/{device}; "
            f"build v{VERSION} from source and set NEMO_RUNTIME_DIR"
        )
    prefix = Path(prefix).resolve()
    marker = prefix / ".polyvox-runtime"
    if marker.is_file() and marker.read_text().strip() == CHECKSUMS[name]:
        return prefix
    if prefix.exists():
        raise ValueError(
            f"{prefix} already exists with another/unverified SDK; choose a new --prefix"
        )
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=prefix.parent, prefix="nemo-install-") as directory:
        root = Path(directory)
        archive = root / name
        with (
            urllib.request.urlopen(
                f"https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v{VERSION}/{name}",
                timeout=120,
            ) as response,
            archive.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        with archive.open("rb") as downloaded:
            if hashlib.file_digest(downloaded, "sha256").hexdigest() != CHECKSUMS[name]:
                raise ValueError("SDK archive checksum mismatch")
        unpack = root / "unpacked"
        unpack.mkdir()
        if extension == "zip":
            with zipfile.ZipFile(archive) as source:
                for member in source.namelist():
                    target = (unpack / member).resolve()
                    if not target.is_relative_to(unpack.resolve()):
                        raise ValueError("Unsafe archive path")
                source.extractall(unpack)
        else:
            with tarfile.open(archive) as source:
                source.extractall(unpack, filter="data")
        entries = list(unpack.iterdir())
        sdk = entries[0] if len(entries) == 1 and entries[0].is_dir() else unpack
        (sdk / ".polyvox-runtime").write_text(CHECKSUMS[name] + "\n")
        os.replace(sdk, prefix)
    return prefix


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device", choices=("cpu", "metal", "cuda", "vulkan", "qualcomm"), default="cpu"
    )
    parser.add_argument("--prefix", type=Path, default=Path(".runtime/nemo"))
    parser.add_argument("--system", choices=("linux", "macos", "windows"))
    parser.add_argument("--arch", choices=("x86_64", "aarch64"))
    args = parser.parse_args()
    print(install(args.device, args.prefix, args.system, args.arch))
