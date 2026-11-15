import io
import json

import pytest

from examples.stream_client import iter_events


@pytest.mark.parametrize("output_format", ["sse", "jsonl"])
def test_client_requires_terminal_success_and_preserves_utf8(output_format):
    events = [{"type": "segment", "segment": {"text": "雪\nhello"}}, {"type": "complete"}]
    data = ""
    for event in events:
        value = json.dumps(event, ensure_ascii=False)
        data += (
            f"event: {event['type']}\ndata: {value}\n\n" if output_format == "sse" else value + "\n"
        )
    assert list(iter_events(io.BytesIO(data.encode()), output_format)) == events
    partial = json.dumps(events[0])
    partial = f"data: {partial}\n\n" if output_format == "sse" else partial + "\n"
    with pytest.raises(RuntimeError, match="without complete"):
        list(iter_events(io.BytesIO(partial.encode()), output_format))


@pytest.mark.parametrize("output_format", ["sse", "jsonl"])
def test_client_rejects_terminal_error(output_format):
    event = {"type": "error", "error": "invalid_media", "status": 422, "request_id": "test"}
    value = json.dumps(event)
    data = f"data: {value}\n\n" if output_format == "sse" else value + "\n"
    with pytest.raises(RuntimeError, match="422.*invalid_media"):
        list(iter_events(io.BytesIO(data.encode()), output_format))
