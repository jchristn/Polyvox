![Polyvox](https://raw.githubusercontent.com/jchristn/Polyvox/main/assets/logo-dark.png)

# Polyvox API v1.0.0

Transcribe audio/video with optional online speaker diarization and optional audio
clips. Choose a readable text stream, complete JSON, JSONL, or SSE. The service
feeds a shared PCM stream to independently replaceable speech-recognition and
diarization providers. Final text and speaker labels arrive together, once per
segment.

## Start here

1. Start Polyvox with `docker compose up --build`, or follow the native setup guide.
2. Import `Polyvox.postman_collection.json` and `Polyvox.local.postman_environment.json`.
3. Select **Polyvox - Local** in the environment selector.
4. Set `base_url` and, if the server requires authentication, the local `api_token` value.
5. For local uploads, set Postman's **Settings > General > Working directory** to
   the project root. The bundled sample then resolves as `tests/fixtures/jfk.wav`.
   You can also select a local file in a request's **Body > form-data > file** row.
6. Send **Service status / Readiness**, then a request in **Transcribe your audio**.

The desktop app can read local files. In the web app, use the Desktop Agent.
Collection/environment imports contain paths, not the audio files themselves.
Do not add a multipart Content-Type header; Postman generates its boundary.

## Variables

Postman uses **double braces**, for example `{{base_url}}` and `{{diarization}}`.
The collection provides defaults, and the selected environment overrides them.
Keep real bearer tokens in local values or your own private environment; the
supplied environment contains an empty, masked token field.

| Variable | Default | Purpose |
| --- | --- | --- |
| `base_url` | `http://127.0.0.1:8000` | Service origin, without a trailing slash; change for staging/production |
| `api_token` | empty | Service bearer token when `API_TOKEN` is configured; not a Postman or Hugging Face token |
| `audio_file` | `tests/fixtures/jfk.wav` | File for editable transcription requests, relative to the working directory |
| `output_format` | `json` | `text`, `json`, `jsonl`, or `sse` for the configured-output request |
| `diarization` | `true` | Enable speaker labels for editable requests |
| `include_audio` | `false` | Include base64 WAV clips in structured responses |
| `fixture_audio_file` | `tests/fixtures/jfk.wav` | Known speech fixture used by the acceptance suite |
| `invalid_audio_file` | `openapi.yaml` | Non-media file used deliberately by error tests |
| `expected_text` | `country` | Recognized word checked only in acceptance requests |
| `expected_language_prefix` | `en` | Language prefix checked only in acceptance requests |

Editable requests use your `audio_file`, `diarization`, and `include_audio`
variables. The configured-output request also uses `output_format`.
The text request explicitly disables audio. Fixed acceptance cases intentionally
keep their format and boolean combinations fixed so that changing an exploratory
variable cannot remove coverage. Both groups reuse `base_url` and `api_token`.
If you select a file through the picker, Postman may replace that request's
`{{audio_file}}` reference with a fixed path; restore it to share the variable again.

## Requests and outputs

Every transcription request is a multipart POST to `/transcribe`, with a required
`file` field. `format`, `diarization`, and `include_audio` may appear in the query
or as multipart text fields. Use each option once; duplicate values are rejected,
including duplicates split between query and body.

| Format | Content-Type | Completion |
| --- | --- | --- |
| `text` | `text/plain` | Timestamped speaker lines, then `# complete` |
| `json` | `application/json` | One complete transcript object |
| `jsonl` | `application/x-ndjson` | One JSON event per line, ending with `complete` |
| `sse` | `text/event-stream` | Named events with JSON `data`, ending with `complete` |

A segment contains `start`, `end`, `len`, `text`, and `speaker`. Times are seconds,
with `len = end - start`. Disabled diarization uses `UNKNOWN`; enabled labels
such as `SPEAKER_00` are local to the session and are estimates, not identities.
Unassigned speech may also be `UNKNOWN`.

When audio is enabled, each structured segment includes `audio` with `encoding`
`base64`, `content_type` `audio/wav`, `sample_rate` 16000, `channels` 1, and `data`.
Decode `data` to obtain a complete PCM16 WAV for that source interval. It contains
the normalized mixed source, not an isolated speaker. Text with audio enabled
returns 400. Audio output is capped by the server's `MAX_AUDIO_BYTES`.

For JSONL/SSE, append each `segment` by its zero-based `id`; all have `final: true`.
`started`, `attempt`, and optional `heartbeat` events precede or accompany results.
An `attempt` can repeat only before any segment is emitted. There is no later
speaker relabeling, automatic replay after publication, or resumable event ID.
Require `complete` and verify `segment_count`. Disconnects or terminal `error`
events leave an incomplete transcript. Postman test scripts inspect the finished
response; the server still emits incremental data.

HTTP accepts an uploaded file, then decodes and processes it. Live microphone
PCM input is available through the Python library, not this multipart endpoint.

## Health, authentication, and recovery

`GET /`, `HEAD /`, and `GET /ready` are public. Other operations inherit the
collection bearer token. An empty token is fine when the service has no
`API_TOKEN`. Readiness checks installed prerequisites and circuit state; it does
not perform a model inference. `/metrics` reports job/circuit state.
`POST /clear-models` succeeds while idle; active work returns 503.

| HTTP status / stream error status | Meaning |
| --- | --- |
| 400 | Missing file, invalid/repeated option, or audio requested with text |
| 401 | Missing/invalid required bearer token |
| 413 | Upload exceeds the server limit |
| 422 | Invalid media, excessive duration, or excessive emitted audio |
| 503 | Busy, backend unavailable, or circuit cooldown; respect Retry-After when present |
| 504 | Processing deadline exceeded |

For JSON, failures use normal HTTP status codes. For text/JSONL/SSE, a response
can start with HTTP 200 and subsequently fail in its terminal marker/event.
A successful HTTP status by itself is therefore insufficient for streams.
Workers are isolated, admission is bounded, and jobs are cancelled on detected
disconnects. Jobs are not persisted across server failure.

## Collection organization

- **Service status**: public health/readiness and authenticated metrics.
- **Transcribe your audio**: editable requests using your variables, with saved
  response examples for JSON, text, SSE, JSONL, and audio clips.
- **Acceptance suite**: 21 fixed scenarios, including every diarization/audio
  combination in SSE/JSONL, form options, authentication policy, malformed media,
  recovery, and model release. Run sequentially against an idle test instance.
  Intentional error responses pass when they match the expected contract.

The default models are Nemotron 3.5 ASR Streaming 0.6B and Nemotron 3 Diarization.
Docker images include both; native installations use the setup guides. Models
and providers are configured on the server, independently of these request options.

[REST API](https://github.com/jchristn/Polyvox/blob/main/REST_API.md) ·
[OpenAPI contract](https://github.com/jchristn/Polyvox/blob/main/openapi.yaml) ·
[Python library](https://github.com/jchristn/Polyvox/blob/main/LIBRARY.md) ·
[Testing](https://github.com/jchristn/Polyvox/blob/main/TESTING.md)
