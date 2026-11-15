# Hardware and runtime support

Python coordinates providers; the native model runtime performs inference.
The supplied adapter targets the public C ABI of
[NeMo-Speech.cpp v0.3.0](https://github.com/NVIDIA/NeMo-Speech.cpp/tree/v0.3.0).
The installer verifies a pinned archive checksum and refuses to overwrite a
different installation. ASR and diarization can use independently selected
devices, with CPU diarization as the default.

| Target | Available path | Verification requirement |
| --- | --- | --- |
| Linux x86_64 / aarch64 CPU | Pinned SDK; amd64/arm64 Docker | Real container smoke test |
| macOS Apple Silicon | Pinned CPU or Metal SDK | Native hardware test for Metal |
| macOS Intel | Pinned CPU SDK | Native CPU integration tests |
| Windows x64 | Pinned CPU/CUDA/Vulkan SDK | Matching DLL runtime and drivers |
| NVIDIA Linux GPU | Pinned CUDA SDK; CUDA container | Compatible NVIDIA driver and real GPU test |
| Vulkan GPU | Matching pinned Linux/Windows archive | Working Vulkan driver and GPU test |
| Qualcomm Adreno | Vulkan adapter with vendor validation | Matching ARM SDK/source build and real Adreno test |
| AMD ROCm/HIP | Custom compatible SDK or provider | No pinned prebuilt ROCm archive; integration required |
| Windows ARM64 CPU/Adreno | Custom SDK/provider | No pinned CPU/Vulkan archive for this target |

CUDA for Linux aarch64 selects the upstream CUDA 13 archive; x86_64 selects its
published CUDA archive. Match drivers to those upstream builds. Docker must
receive the GPU through the NVIDIA Container Toolkit. It cannot provide an
Apple Metal device. Qualcomm support here means Adreno Vulkan, **not Hexagon
NPU/QNN**. ROCm and unsupported prebuilt combinations are extension paths,
not verified turnkey installations.

```bash
python scripts/install_runtime.py --device metal --prefix .runtime/metal
export NEMO_RUNTIME_DIR="$PWD/.runtime/metal"
export DEVICE=metal
export RUN_HARDWARE=1
uv run --no-sync pytest -m hardware -v
```

Replace `metal` with an available backend on its actual host. Use a separate
prefix for each SDK. The installer supports CPU, Metal, CUDA, Vulkan, and the
Qualcomm Vulkan alias where an archive exists. For a custom build, install the
SDK's shared libraries and companion ggml backends together, then point
`NEMO_RUNTIME_DIR` at its root. Implement a separate provider if the model/runtime
does not expose the supported C ABI; see [LIBRARY.md](LIBRARY.md).

`GPU_DEVICE` selects a GPU ordinal. The adapter enumerates native ggml devices
and validates the requested backend/vendor before model creation. An unavailable
GPU is an error, not silently reported as accelerated. Explicit
`CPU_FALLBACK=true` permits an eligible ASR retry before any segment is emitted;
metadata identifies the actual device. Configure `DIARIZATION_DEVICE` separately.

The default Q8 models total about 849 MB on disk. Peak RAM/VRAM includes weights,
streaming caches, decoding, context, and optional audio. Measure throughput and
memory on representative recordings. ASR endpointing, diarization buffering,
and CPU/GPU scheduling all affect caption latency; no universal real-time or
speaker-accuracy guarantee is made.

Local acceptance has exercised macOS ARM64 CPU/Metal and Linux ARM64 CPU,
plus Linux AMD64 CPU under emulation. Windows, NVIDIA, ROCm, and Qualcomm need
their own hardware acceptance. CI definitions are not evidence those remote
runs have executed. See [TESTING.md](TESTING.md).
