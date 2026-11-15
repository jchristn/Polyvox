"""HTTP encodings of the public event iterator."""

import json

from flask import Response

from .output import format_transcript


def encode_event(event: dict, output_format: str) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if output_format == "text":
        if event["type"] == "segment":
            return format_transcript([event["segment"]]) + "\n"
        if event["type"] == "complete":
            return "# complete\n"
        if event["type"] == "error":
            return "# error " + data + "\n"
        return "\n" if event["type"] == "heartbeat" else ""
    if output_format == "jsonl":
        return data + "\n"
    return f"event: {event['type']}\ndata: {data}\n\n"


def stream_response(service, source, cleanup, request_id, output_format, **options):
    events = service.stream(source, cleanup=cleanup, request_id=request_id, **options)

    def generate():
        try:
            for event in events:
                yield encode_event(event, output_format)
        finally:
            events.close()

    response = Response(
        generate(),
        mimetype={
            "text": "text/plain",
            "sse": "text/event-stream",
            "jsonl": "application/x-ndjson",
        }[output_format],
        headers={"X-Accel-Buffering": "no"},
    )
    response.call_on_close(events.close)
    return response
