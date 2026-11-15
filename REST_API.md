# REST API — v1.0.0

The machine-readable contract is [openapi.yaml](openapi.yaml). Start with
`API_MODE=true uv run --no-sync polyvox`. Native default address:
`http://127.0.0.1:8000`. Docker exposes port 8000. Set `API_TOKEN` to require
`Authorization: Bearer <token>` on protected endpoints; liveness/readiness are public.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET / HEAD | `/` | Liveness; no model initialization |
| GET | `/ready` | Local prerequisites and circuit state; not an inference benchmark |
| GET | `/metrics` | Job/circuit counters and configured device |
| POST | `/transcribe` | Multipart upload and chosen transcript format |
| POST | `/clear-models` | Confirm idle model release; 503 if a job is active |

Every job owns its model processes; models are released on job exit.

## Request options

Upload the required multipart field `file`. Options may appear in the query
string **or** multipart body. Repeating an option, including across both
locations, returns 400. JSON request bodies are not accepted for file uploads.

| Option | Values | Default |
| --- | --- | --- |
| `format` | `text`, `json`, `jsonl`, `sse` | `text` |
| `diarization` | boolean | server `DIARIZATION` (false) |
| `include_audio` | boolean | server `INCLUDE_AUDIO` (false) |

Booleans accept true/false, 1/0, yes/no, case-insensitively. Invalid values return
400. Audio is available only in JSON/JSONL/SSE; text with audio enabled returns
400. Options apply to that request without changing server defaults.

```bash
curl -N -F 'file=@recording.wav' \
  'http://localhost:8000/transcribe?format=sse&diarization=true&include_audio=true'

curl -F 'file=@recording.wav' -F 'format=json' -F 'diarization=false' \
  -F 'include_audio=true' http://localhost:8000/transcribe
```

Uploaded local media is decoded once to mono 16 kHz PCM, then fed to resident
ASR and optional online diarization together. HTTP upload/decode completes
before inference; live microphone PCM input is available through the Python
[Engine](LIBRARY.md). There is no WebSocket or resumable upload endpoint.

## Segments and audio

Every final segment has `start`, `end`, `len` in seconds (`len = end - start`),
`text`, and `speaker`. With diarization disabled or no confident overlapping
speaker turn, the label is `UNKNOWN`. Enabled labels such as `SPEAKER_00` are
session-local estimates, not identities. A speaker change can split an utterance.
Overlapping speech is assigned to the greatest word/turn overlap; this does not
produce separate transcripts or separate audio channels for simultaneous voices.

When `include_audio=true`, each segment additionally contains:

```json
{
  "audio": {
    "encoding": "base64",
    "content_type": "audio/wav",
    "sample_rate": 16000,
    "channels": 1,
    "data": "<base64-encoded WAV bytes>"
  }
}
```

`data` above is an illustrative placeholder. The real value decodes to a complete
PCM16 WAV for `[start, end)`, cropped from the normalized mixed recording. When
disabled, `audio` is absent. Output base64 audio is capped across the job by
`MAX_AUDIO_BYTES` (64 MiB default); reaching the cap fails the job. Base64 adds
approximately one third to binary size. Large clips also affect proxy/client
buffer limits.

## Text stream

`Content-Type: text/plain; charset=utf-8`. Each segment is a complete line:

```text
[0.0-1.2 SPEAKER_00] Hello there.
[1.5-2.1 SPEAKER_01] Welcome.
# complete
```

Blank lines are heartbeats. Require the final `# complete` line. On failure,
`# error {"type":"error",...}` replaces completion. A closed connection without
a terminal marker means incomplete output. Text is diarized when enabled, and
has `UNKNOWN` labels otherwise. CLI text files contain transcript lines only.

## Full JSON

`Content-Type: application/json`. The response is returned after both models
finish. This abbreviated example omits optional audio and some metadata:

```json
{
  "segments": [
    {"start": 0.0, "end": 1.2, "len": 1.2, "text": "Hello there.", "speaker": "SPEAKER_00"}
  ],
  "segment_count": 1,
  "language": "en-US",
  "metadata": {
    "backend": "streaming-engine",
    "asr_provider": "nemo",
    "diarization_provider": "nemo",
    "device": "cpu",
    "diarization_device": "cpu",
    "diarization": true,
    "include_audio": false,
    "alignment": "word-timestamps",
    "single_pass": true
  }
}
```

Metadata also includes configured model paths, requested ASR device, and attempts.
Disabled diarization has null provider/model/device metadata. Complete JSON
buffers all segments; choose an event stream for incremental consumption.

## JSONL and SSE

JSONL uses `application/x-ndjson`: one compact JSON event per line. SSE uses
`text/event-stream`: `event: <type>` and `data: <JSON>` followed by a blank line.
Both transports carry the same records. Every record contains `request_id`.
This illustrative JSONL sequence abbreviates completion metadata:

```jsonl
{"type":"started","request_id":"r1"}
{"type":"attempt","request_id":"r1","attempt":1,"reset":true,"requested_device":"cpu","device":"cpu"}
{"type":"segment","request_id":"r1","attempt":1,"id":0,"final":true,"segment":{"start":0.0,"end":1.2,"len":1.2,"text":"Hello there.","speaker":"SPEAKER_00"}}
{"type":"segment","request_id":"r1","attempt":1,"id":1,"final":true,"segment":{"start":1.5,"end":2.1,"len":0.6,"text":"Welcome.","speaker":"SPEAKER_01"}}
{"type":"complete","request_id":"r1","segment_count":2,"language":"en-US","metadata":{"single_pass":true}}
```

An SSE segment is framed as:

```text
event: segment
data: {"type":"segment","request_id":"r1","attempt":1,"id":0,"final":true,"segment":{"start":0.0,"end":1.2,"len":1.2,"text":"Hello there.","speaker":"SPEAKER_00"}}

```

Segments are append-only, with contiguous zero-based IDs and `final: true`.
Text and speaker labels arrive together. There are no provisional segments or
later diarization updates. With audio enabled, the same event's `segment`
contains the `audio` object. With diarization disabled, words can be released
without waiting for the diarizer watermark.

`heartbeat` events arrive during idle waits (nominally every five seconds).
`attempt` may repeat only before the first segment; `reset` therefore never
discards published transcript content. Once any segment has been published,
backend failure ends the stream with `error`; the service does not replay audio
or duplicate segments through an automatic retry. `complete` is the only success
signal; compare `segment_count` with received segments. An error record contains
`error`, `status`, optional `detail`, and sometimes `retry_after`. Unexpected
connection closure is not success. SSE has no resumable event IDs/Last-Event-ID.

Use POST `fetch` and a streaming UTF-8 decoder in browsers; `EventSource` cannot
send multipart POST. Network chunks are not event boundaries. Disable proxy
response buffering and use suitable idle/request timeouts. See the maintained
[Python streaming client](examples/README.md) and [Postman checks](postman/README.md).

## Errors, safeguards, and limits

Option, authentication, upload, and prerequisite errors before streaming use
normal HTTP JSON errors. For full JSON, processing errors also use HTTP statuses.
For text/JSONL/SSE, HTTP 200 can be followed by a terminal error because headers
have already been sent. Always consume the terminal record/marker.

| Status | Examples |
| --- | --- |
| 400 | Missing file, invalid/repeated option, text with audio |
| 401 | Missing or invalid configured bearer token |
| 413 | Upload exceeds `MAX_UPLOAD_BYTES` |
| 422 | Invalid/unsupported media, duration or audio-output limit |
| 503 | Capacity, circuit cooldown, unavailable/misconfigured backend |
| 504 | Processing deadline exceeded |

Defaults: upload 512 MiB, duration 7200 s, job deadline 3600 s, no pending jobs,
queue wait 5 s, one retry, CPU fallback disabled, circuit opens after three
backend failures for 30 s. `MAX_PENDING` allows a bounded queue; one inference
job runs at a time per service. Streaming buffers at most 16 events and applies
backpressure. Disconnect detection cancels workers and removes temporary files;
proxies can delay detection. Jobs are not persisted across server/host failure.
Set external disk/memory limits and supervise the service.

Model/device selection is server configuration, not request-supplied code.
`MODEL_PATH`, `DIARIZATION_MODEL`, `ASR_PROVIDER`, `DIARIZATION_PROVIDER`,
`NEMO_RUNTIME_DIR`, `DEVICE`, `DIARIZATION_DEVICE`, `GPU_DEVICE`, and `LANGUAGE`
select providers. `SEGMENT_SECONDS` (default 8; range 1–30) bounds ASR endpoint
intervals; shorter intervals can reduce recognition context. The diarization
watermark uses `DIARIZATION_HOLDBACK` (default and native minimum 1.2 s). `CPU_FALLBACK=true` permits
eligible ASR retries on CPU and reports the actual device; it does not convert
a GPU-only diarizer. See `polyvox/config.py` for all validated settings.
