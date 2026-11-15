# Native Windows

Install Python 3.12–3.14, uv, FFmpeg/FFprobe on PATH, and the Microsoft Visual C++
runtime required by the upstream SDK. In PowerShell, from the project directory:

```powershell
uv sync --locked
uv run --no-sync python scripts/install_runtime.py --device cpu --prefix .runtime/nemo
uv run --no-sync python scripts/download_model.py nemotron-asr
uv run --no-sync python scripts/download_model.py nemotron-diar
uv run --no-sync polyvox --doctor
$env:API_MODE = "true"
uv run --no-sync polyvox
```

The pinned release provides Windows x64 CPU/CUDA/Vulkan SDKs. Native Windows
ARM64 CPU/Adreno requires a compatible source-built SDK or custom provider;
there is no matching pinned CPU/Vulkan archive in this release. Do not interpret
Python ARM64 support as proof of native accelerator availability. WSL2/Linux
containers are an alternative for supported Linux targets.

Choose a new `--prefix` when installing another SDK and set
`$env:NEMO_RUNTIME_DIR = "..."` and `$env:DEVICE = "cuda"` or `"vulkan"`.
Qualcomm mode validates that the selected Vulkan device is Adreno; it does not
use Hexagon/QNN. See [HARDWARE.md](HARDWARE.md).

For file mode, unset `API_MODE` and follow [EXAMPLE_CLI.md](EXAMPLE_CLI.md).
Subprocess timeout/shutdown uses Windows process-tree termination. Abrupt host
or supervisor failure still requires OS-level service supervision.
