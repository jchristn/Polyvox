# Changelog

## 1.0.0 — Initial release

- Shared stateful PCM engine with independently replaceable ASR and diarization providers.
- Nemotron streaming speech recognition and optional online speaker diarization.
- Text streaming, complete JSON, and append-only JSONL/SSE with final speaker labels.
- Per-request diarization and optional base64 WAV clips in structured segments.
- Public Python file/event APIs and live PCM sessions; HTTP client example.
- Isolated workers, bounded queues and output, deadlines, cancellation, circuit recovery,
  and retries before the first published segment.
- Python 3.12–3.14, Linux amd64/arm64 containers, and configurable native accelerators.
- Checksum-pinned runtime/models, OpenAPI, Postman, automated tests, and CI/release workflows.
- Server publishing helpers use Docker Build Cloud for amd64/arm64 images tagged with a supplied version and latest.
- CPU and CUDA images include all runtime dependencies and both checksum-verified default models; no host model mount is required.
