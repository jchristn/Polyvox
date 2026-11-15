# Native Linux

Use Python 3.12–3.14 and install uv. Debian/Ubuntu prerequisites:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg libgomp1 ca-certificates
uv sync --locked
uv run --no-sync python scripts/install_runtime.py --device cpu --prefix .runtime/nemo
uv run --no-sync python scripts/download_model.py nemotron-asr
uv run --no-sync python scripts/download_model.py nemotron-diar
uv run --no-sync polyvox --doctor
API_MODE=true uv run --no-sync polyvox
```

The pinned SDK installer selects x86_64 or aarch64 for the host. Official
prebuilt libraries require a compatible modern glibc system; use the supplied
Debian Trixie container if your distribution's ABI is older. See
[GETTING_STARTED.md](GETTING_STARTED.md) for Docker on both architectures.

For CUDA or Vulkan, install the matching driver, use the corresponding
`--device` and a new SDK prefix, and set `DEVICE` and `NEMO_RUNTIME_DIR`.
ROCm requires a compatible custom SDK/provider; it is not supplied by the
pinned prebuilt archive installer. See [HARDWARE.md](HARDWARE.md) for the exact
support boundary and required acceptance tests.
