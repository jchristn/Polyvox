# Docker setup

Install Docker with Compose. Use a recent Docker Desktop on macOS/Windows or
Docker Engine on Linux. No host Python or model installation is required. Run from the
project directory:

```bash
docker compose up --build
curl http://localhost:8000/ready
curl -N -F 'file=@recording.wav' \
  'http://localhost:8000/transcribe?format=sse&diarization=true'
```

The default CPU image supports Linux amd64 and arm64/v8. CPU Compose files use
`jchristn77/polyvox-server:v1.0.0`; set `IMAGE_TAG` to select another tag.
Both CPU and CUDA Dockerfiles install all application dependencies, FFmpeg,
the matching native SDK, and the default ASR and diarization models. The model
files total about 849 MB and are included in the image, even when diarization
is disabled for a request. Downloads happen during the build and are verified
against pinned SHA-256 checksums. A fresh container is ready without a model
volume, startup downloads, or a Hugging Face token. First builds need network
access; subsequent builds can reuse the model layer.

Use `docker compose -f compose-cuda-api.yaml up --build` on an NVIDIA host with
the Container Toolkit and a compatible driver. GPU inference must be validated
on that host; a successful build is not proof of acceleration. Apple Metal
requires native macOS, as described in [RUN_ON_MAC.md](RUN_ON_MAC.md).

## Configuration

Compose listens on localhost:8000. Set `API_TOKEN` before startup to require a
bearer token. For example, read a secret into your environment using your normal
secret manager; do not put it in a collection or checked-in file. Supply it to
clients via `Authorization: Bearer <token>`.

The included models live under `/models/`. To use replacements, explicitly
mount your files read-only at another path (for example `/custom-models`) and
set `MODEL_PATH` / `DIARIZATION_MODEL` to those container paths. Avoid mounting
an empty directory over `/models`, which hides the included weights. Native
host absolute paths are not valid container paths. Environment options include `DIARIZATION`,
`INCLUDE_AUDIO`, `MODEL_PATH`, `DIARIZATION_MODEL`, `JOB_TIMEOUT`,
`MAX_UPLOAD_BYTES`, and `MAX_DURATION`; see the Compose files and
[API reference](REST_API.md). Request flags override diarization/audio defaults.
Text plus enabled audio is rejected, so use a structured format for clips.

Images use a non-root user (uid 10001). The included weights are readable and
root-owned. Input or custom-model mounts must be readable;
output mounts must be writable by that user. Models and normalized PCM need
additional RAM/disk beyond the download size. Set deployment resource limits
appropriate to your recordings. Use a TLS reverse proxy if exposing the service,
and disable response buffering for streams.

## Batch CLI

```bash
mkdir -p input output
# Put recording.wav in input/ and grant the container user output write access.
docker compose -f compose-cpu.yaml run --rm transcriber \
  --input /data/input/recording.wav --output-json /data/output/transcript.json \
  --output-txt /data/output/transcript.txt --diarize --include-audio
```

Use `compose-cuda.yaml` for the GPU CLI. See [EXAMPLE_CLI.md](EXAMPLE_CLI.md).
Stop the API with `docker compose down`. In-flight jobs are cancelled, not
persisted. `/` reports process liveness; `/ready` checks local prerequisites and
circuit state. It does not load models or prove accelerator readiness.

## Build each architecture

```bash
docker build --platform linux/amd64 -f dockerfile-cpu -t polyvox-server:amd64 .
docker build --platform linux/arm64/v8 -f dockerfile-cpu -t polyvox-server:arm64 .
```

Run [container acceptance](TESTING.md) for each image. Emulation can establish
correctness but cannot establish native throughput. The canonical published image is the portable CPU server,
`jchristn77/polyvox-server`. CUDA remains available through its local Dockerfile
and Compose configuration.


## Publish the server image

The publishing helpers follow a single required tag argument. The initial
release tag is `v1.0.0`:

```bash
./build-server.sh v1.0.0
```

Windows Command Prompt / PowerShell:

```powershell
.\build-server.bat v1.0.0
```

Both use Armada's existing Docker Build Cloud builder,
`cloud-jchristn77-jchristn77`, to build `linux/amd64` and `linux/arm64/v8` and
**push both** `jchristn77/polyvox-server:v1.0.0` and
`jchristn77/polyvox-server:latest`. Supplying another tag replaces `v1.0.0` in
that pair; `latest` is always updated. The helper uses `dockerfile-cpu` with
`API_MODE=true`, so the published image starts the HTTP server by default.
The two default models are included in the published image.

Sign in with `docker login` using an account authorized for the builder and
image repository. If this builder is not configured on the machine, connect it
once with `docker buildx create --name cloud-jchristn77-jchristn77 --driver cloud
jchristn77/jchristn77`. The scripts require the named builder and do not create a
local substitute. See [Docker Build Cloud setup](https://docs.docker.com/build-cloud/ci/)
for compatible Buildx versions and authentication.

These are publishing commands, not local validation commands. The tag-triggered
release workflow runs CI first, connects the same cloud builder, and invokes the
same helper. Configure the repository secret `DOCKER_ACCESS_TOKEN` with Docker
Hub write access and access to the cloud builder before running a release.
The ordinary `main` push runs CI only; it does not publish an image.
