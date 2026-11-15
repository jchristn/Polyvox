# Streaming HTTP client

`stream_client.py` is a Python standard-library client and reusable
`transcribe_events` iterator. The installed Python package also provides a
[first-class local library](../LIBRARY.md); there are no separate language SDKs.

```bash
python examples/stream_client.py recording.wav --format sse --diarization --include-audio
python examples/stream_client.py recording.wav --format jsonl --no-diarization --no-include-audio
```

Use `--url http://127.0.0.1:8000` to choose the server. Set `API_TOKEN` in the
client environment for bearer authentication. Uploads and responses are read
in bounded chunks. The client prints one JSON event per line and exits nonzero
on HTTP errors, terminal errors, or a connection ending without `complete`.

```python
from contextlib import closing
from examples.stream_client import transcribe_events

with closing(
    transcribe_events(
        "recording.wav",
        "http://127.0.0.1:8000",
        "sse",
        diarization=True,
        include_audio=True,
    )
) as events:
    for event in events:
        print(event)
```

Use `closing` when you might stop early. Each segment arrives once, finalized
with its speaker and optional clip. Append segments by zero-based `id`.
Attempts can repeat before any segment is published; there is no replay after
published content. Require the terminal `complete` event and expected segment
count. [REST_API.md](../REST_API.md) specifies the envelopes and error behavior.

Browser clients should POST with `fetch`, read `response.body`, and retain
incomplete UTF-8/line/event fragments between network chunks. Native
`EventSource` cannot send multipart POST. Use `AbortController` to cancel.
`curl -N` disables curl's output buffering for interactive exploration.
