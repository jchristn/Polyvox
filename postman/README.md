# polyvox API collection

`collections/Polyvox` is a local Postman v3 collection matching
[openapi.yaml](../openapi.yaml), with maintained assertions. Import the OpenAPI
file into the app for exploration; those generated requests do not include the
collection's custom tests. No workspace publication is needed.

## What this collection exercises

The collection is named **polyvox v1.0 — streaming speech API** in Postman.
Requests are labeled by output format, speaker setting, and audio setting.
`openapi.yaml` defines the contract; this collection adds runnable examples and
assertions for the behavior callers depend on.

| Requests | Expected behavior |
| --- | --- |
| Text | Final caption lines followed by `# complete` |
| JSON | A full transcript; the body-options example enables speakers and WAV clips |
| SSE and JSONL | All four combinations of diarization/audio; unique final IDs and terminal success |
| Invalid media stream | Terminal error after HTTP headers, with no successful completion |
| Readiness and recovery | Prerequisites, circuit metrics, and successful inference after rejected media |
| Authentication | Service bearer access when configured; public health endpoints |

`diarization` and `include_audio` are independent request options. `len` equals
`end - start` in seconds. Clips contain the normalized source interval, including
any background or overlapping voices. Segment records arrive finalized;
consumers do not replace earlier text or wait for a whole-file speaker pass.
The HTTP input remains an uploaded file; live PCM input is provided by the
[Python library](../LIBRARY.md).

## Run against a local instance

Install Python dependencies, FFmpeg, the native SDK, and both default models as
shown in [TESTING.md](../TESTING.md). Start an idle test API from the project root:

```bash
export NEMO_RUNTIME_DIR="$PWD/.runtime/nemo"
export MODEL_PATH="$PWD/models/nemotron-asr.gguf"
export DIARIZATION_MODEL="$PWD/models/nemotron-diar.gguf"
export DEVICE=cpu
export DIARIZATION=false
export INCLUDE_AUDIO=false
API_MODE=true uv run --no-sync polyvox
```

Use PowerShell environment syntax on Windows. The default URL is
`http://127.0.0.1:8000`. Install a Postman CLI supporting local v3 collections
(validated with 1.75.0), then run in a second terminal:

```bash
postman collection lint postman/collections/Polyvox
postman environment lint postman/environments/local.environment.yaml --fail-severity warning
postman collection run postman/collections/Polyvox \
  --environment postman/environments/local.environment.yaml \
  --working-dir . --no-insecure-file-read \
  --timeout-request 120000 --no-report-events
```

The working directory must be the project root so requests can read
`tests/fixtures/jfk.wav` and `openapi.yaml` (used intentionally as invalid media).
Let Postman generate the multipart boundary. Override the URL with
`--env-var base_url=http://127.0.0.1:8001` if needed. Increase timeouts on slow hosts.

Expect **21 requests, 93 passing assertions, zero failures**, and exit code 0.
Checks cover health, authentication policy, errors, recovery, text completion,
JSON, all four diarization/audio combinations for SSE and JSONL, body options,
unique final segment IDs, clip metadata, lengths, and idle model release.
The collection performs real inference and calls `/clear-models`; run on a test
instance. Expected 400/401/422 responses count as passing when asserted correctly.

For authentication, set `API_TOKEN` on the server and provide the matching
`api_token` Postman environment variable through a private environment or secret
mechanism. Keep credentials out of tracked files and command history. The
collection checks valid bearer access and unauthenticated rejection when a token
is configured; otherwise the same policy check expects access. Health endpoints
remain public. Repeat once without and once with authentication.

`--no-report-events` prevents cloud run reporting. No login, workspace binding,
publication, or collection synchronization is necessary. CLI 1.75.0 may print
a login notice while still supporting local runs. Judge results by assertions
and exit code. Postman reads completed streams; pytest independently checks
incremental timing, cancellation, retries, process failures, and backpressure.
