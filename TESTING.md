# Testing

Run commands from the project root. Python 3.12–3.14 is supported. Tests distinguish
injected provider behavior from real native inference and hardware acceptance.
No gated models, account, token, or PyTorch installation is needed.

## Fast suite

```bash
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest -m 'not integration and not hardware' --cov=polyvox
uv build
```

This covers API options and errors, authentication, OpenAPI schemas, independent
provider replacement, word timestamps and speaker splitting, exact WAV clips,
audio/input limits, streaming delivery before completion, backpressure, client
disconnects, retries before publication, no retry after a published segment,
circuit recovery, subprocess-tree cancellation, and atomic output staging.
Runtime/model download tests verify checksums and failure cleanup. Mock providers
prove contracts and control flow; they do not prove recognition quality.

To focus on the model-independent engine and transports:

```bash
uv run --no-sync pytest tests/test_pipeline.py tests/test_streaming.py \
  tests/test_streaming_http.py tests/test_stream_client.py -v
```

## Real CPU inference

Install FFmpeg/FFprobe using the OS setup guide, then:

```bash
uv run --no-sync python scripts/install_runtime.py --device cpu --prefix .runtime/nemo
uv run --no-sync python scripts/download_model.py nemotron-asr
uv run --no-sync python scripts/download_model.py nemotron-diar
export NEMO_RUNTIME_DIR="$PWD/.runtime/nemo"
export MODEL_PATH="$PWD/models/nemotron-asr.gguf"
export DIARIZATION_MODEL="$PWD/models/nemotron-diar.gguf"
export RUN_INTEGRATION=1
uv run --no-sync pytest -m integration -v
```

PowerShell uses `$env:NAME = "value"` instead of `export`. A different installed
SDK can be selected with `NEMO_RUNTIME_DIR`; never overwrite an existing different
runtime. Both models total about 849 MB and are loaded from local files.

The 16 integration cases exercise real ASR and diarization through JSON, SSE,
and JSONL for every diarization/audio flag combination, text with and without
speakers, invalid-media recovery, duration rejection, and live PCM emission
before EOF. Tests validate recognized words, segment durations, unique final
IDs, exact decoded WAV durations, terminal success, and OpenAPI schemas.
The fixture checks functionality, not multilingual accuracy or diarization
error rate on overlapping conversations.

## Accelerator acceptance

Install the matching SDK/driver on the actual device, as described in
[HARDWARE.md](HARDWARE.md). For Apple Silicon:

```bash
python scripts/install_runtime.py --device metal --prefix .runtime/metal
export NEMO_RUNTIME_DIR="$PWD/.runtime/metal"
export DEVICE=metal
export RUN_HARDWARE=1
uv run --no-sync pytest -m hardware -v
```

The hardware test requires real backend selection and recognized speech with
diarization enabled. CPU fallback is disabled. Repeat on CUDA, Vulkan, Qualcomm,
or a compatible custom ROCm setup. Do not claim accelerator support from passing
CPU tests or from an image build. To run **every test** with real models and a
Metal host, set both `RUN_INTEGRATION=1` and `RUN_HARDWARE=1`, select the Metal
SDK and `DEVICE=metal`, then run `uv run --no-sync pytest`. With no native assets
configured, integration/hardware tests skip deliberately; a skipped test is not
a passed hardware check.

For quality/performance acceptance, use consented multilingual and multi-speaker
recordings, including overlap, long silences, rapid speaker changes, and background
noise. Record WER/DER or manually checked references, time to first final segment,
real-time factor, peak RAM/VRAM/disk, model checksums, device/driver, and runtime.
Test 10-minute and two-hour sessions. Verify speaker continuity across endpoint
boundaries and long-stream compaction. Eight-speaker capacity is a model limit,
not a promise of reliable labeling in every recording.

## Both Linux container architectures

Build/run on each architecture; the Dockerfiles download and include both
models, so no host model setup is needed:

```bash
docker build --platform linux/arm64/v8 -f dockerfile-cpu -t transcriber:test-arm64 .
python scripts/container_smoke.py --image transcriber:test-arm64
docker build --platform linux/amd64 -f dockerfile-cpu -t transcriber:test-amd64 .
python scripts/container_smoke.py --image transcriber:test-amd64
```

The script starts an isolated non-root container on an ephemeral localhost port,
asserts that the container has no host/volume mounts, checks readiness, rejects
corrupt media, and verifies real JSON/SSE/JSONL output using the included models
with diarization and audio, final IDs, durations, and terminal success. A second
fresh container transcribes and diarizes the fixture with `--network none` and
no mounts, proving that runtime inference needs no downloads. Containers
are removed even on failure. QEMU emulation is useful for correctness but not
performance measurement. For CUDA, build `dockerfile-cuda`, run with `--gpus all`
on an NVIDIA host, and run real hardware/API acceptance; the CPU smoke script
is intentionally specific to CPU images.

## HTTP clients and Postman

Import the collection/environment JSON files described in
[postman/README.md](postman/README.md). The full importable collection runs 30
requests and 129 assertions; its fixed Acceptance suite runs 21 requests and 93
assertions. Test with and without bearer authentication against an idle service.
Run the [Python example](examples/README.md) in SSE and JSONL modes with both flags.
Postman validates completed responses; pytest separately verifies incremental
delivery, backpressure, and socket cancellation through Waitress.

## Recovery acceptance

Use an isolated test deployment:

1. Send a second job while busy with `MAX_PENDING=0`; expect 503 while liveness stays up.
2. Set a short `JOB_TIMEOUT`; verify timeout, process cleanup, and recovery on a later request.
3. Kill an inference worker before it emits a segment; an eligible retry must use a fresh process.
4. Kill it after a segment; require terminal error with no replay/duplicate segments.
5. Trigger consecutive backend failures; verify readiness fails during cooldown and recovers.
6. Remove/restore a model; liveness remains available and readiness reflects the change.
7. Disconnect a slow streaming consumer; verify cancellation and temporary-file cleanup.
8. Exceed upload, duration, or audio-output limits; verify bounded failure and later recovery.
9. Send shutdown during inference; check child processes on the target OS and behind your proxy.

Streams are incomplete without their success marker. Jobs are not durable or
resumable after host failure. Configure OS/container supervision and resource
limits separately.

## CI/CD

`.github/workflows/ci.yml` runs lint, package builds, and fast tests on Python
3.12/3.13/3.14 across Linux amd64/ARM64, Windows, and macOS. Separate jobs run
native Windows/macOS inference and both Linux container acceptance suites.
`hardware.yml` is manual on dedicated `transcriber-<device>` self-hosted runners
with the matching runtime at `/opt/nemo`; never run untrusted PR code there.
`release.yml` runs CI before invoking `build-server.sh` on version tags. It uses
`cloud-jchristn77-jchristn77` to publish `jchristn77/polyvox-server` for both Linux
architectures under the supplied version and `latest`. Configure the
`DOCKER_ACCESS_TOKEN` repository secret first. The published CPU server defaults
to API mode; CUDA images remain local builds. Dependabot proposes dependency updates.

`tests/test_build_server.py` verifies the Bash helper's builder, platforms, both
tags, server mode, working directory, input validation, and failure exit codes
using a fake Docker executable. It never contacts Build Cloud or publishes.
Run `shellcheck build-server.sh` for shell lint. The Windows batch helper requires
separate Windows execution; its POSIX tests skip on Windows.

These files require a configured GitHub repository to execute remotely. Local
validation does not imply a GitHub workflow has run. No commits, pushes, or
publications are required to run the local tests.
