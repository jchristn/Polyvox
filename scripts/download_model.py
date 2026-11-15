#!/usr/bin/env python3
"""Explicit, checksum-verified model download. Never performed inside an HTTP request."""

import argparse
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

MODELS = {
    "nemotron-en": {
        "sha256": "d9a01898d2a611c8764e23a1c2f45e70bbd5a425dc4de93692ac951dd603812d",
        "url": "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b/resolve/"
        "ebe59e5a817142986528bbbee5dba8db7b38ed50/"
        "nemotron-speech-streaming-en-0.6b.q8_0.gguf",
    },
    "nemotron-asr": {
        "sha256": "a5c435f294eea8f88ce68dd27b8c3bfea7f777cb2fbba04fcd30eaa555f429ae",
        "url": "https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/1c8deaecc64b91f034d73e08dd8b64625eb3395d/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf",
    },
    "nemotron-diar": {
        "sha256": "08456d9e22cd9a323c0364d98375f3746d6e68507ebb705cd46438c534c7a3a1",
        "url": "https://huggingface.co/nvidia/Nemotron-3-Diarization/resolve/f667ed73aee57d40cc39428eb768b4fd87a0a29e/Nemotron-3-Diarization.q8_0.gguf",
    },
}


def download(name: str, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.gguf"
    expected = MODELS[name]["sha256"]
    if target.exists():
        with target.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == expected:
                return target
        raise ValueError(f"Existing model has wrong checksum: {target}; move it aside and retry")
    url = MODELS[name]["url"]
    partial = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as file:
            partial = Path(file.name)
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    file.write(chunk)
            if digest.hexdigest() != expected:
                raise ValueError("Downloaded model checksum mismatch")
        # These public model weights must be readable by the non-root container UID.
        # NamedTemporaryFile otherwise leaves mode 0600 on native Linux bind mounts.
        partial.chmod(0o644)
        os.replace(partial, target)
        return target
    finally:
        if partial:
            partial.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=MODELS, default="nemotron-asr", nargs="?")
    parser.add_argument("--directory", type=Path, default=Path("models"))
    args = parser.parse_args()
    print(download(args.model, args.directory))
