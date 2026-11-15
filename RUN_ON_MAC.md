# Native macOS

Install Python 3.12–3.14, uv, and FFmpeg (`brew install ffmpeg uv`). From the
project directory:

```bash
uv sync --locked
uv run --no-sync python scripts/install_runtime.py --device metal --prefix .runtime/nemo
uv run --no-sync python scripts/download_model.py nemotron-asr
uv run --no-sync python scripts/download_model.py nemotron-diar
export DEVICE=metal
uv run --no-sync polyvox --doctor
API_MODE=true uv run --no-sync polyvox
```

Metal requires Apple Silicon and native macOS. Intel Macs can install with
`--device cpu` and set `DEVICE=cpu`. Use a different `--prefix` when installing
a second SDK, then set `NEMO_RUNTIME_DIR` to that directory. The installer will
not overwrite a different or unverified installation. If Python reports a TLS
certificate error, repair its CA configuration; do not disable verification.

ASR and diarization devices are independent. `DIARIZATION_DEVICE=cpu` is the
default. A request with `diarization=true` enables the online model. Enable
`DIARIZATION_DEVICE=metal` only after running acceptance on that configuration.
Docker on macOS provides a Linux CPU environment and cannot expose Metal.

For a file, run the [CLI example](EXAMPLE_CLI.md). For actual accelerator
verification, follow [TESTING.md](TESTING.md); `--doctor` checks files and tools
without loading the models.
