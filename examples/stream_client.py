#!/usr/bin/env python3
"""Upload a file and print SSE or JSONL event records without extra dependencies."""

import argparse
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path


def iter_events(lines, output_format):
    """Consume this service's single-line JSON event protocol; require completion."""
    completed = False
    for raw in lines:
        line = raw.decode("utf-8").strip()
        if output_format == "sse":
            if not line.startswith("data: "):
                continue
            line = line[6:]
        if not line:
            continue
        event = json.loads(line)
        if event["type"] == "error":
            raise RuntimeError(
                f"Transcription failed ({event['status']}): {event['error']}; "
                f"request_id={event['request_id']}"
            )
        completed = event["type"] == "complete"
        yield event
        if completed:
            return
    if not completed:
        raise RuntimeError("Stream ended without complete; transcript is incomplete")


def transcribe_events(
    path,
    base_url="http://127.0.0.1:8000",
    output_format="sse",
    token="",
    *,
    diarization=False,
    include_audio=False,
):
    if output_format not in {"sse", "jsonl"}:
        raise ValueError("Streaming format must be sse or jsonl")
    path = Path(path)
    boundary = uuid.uuid4().hex
    prefix = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="upload"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()

    def body():
        yield prefix
        with path.open("rb") as source:
            while chunk := source.read(65536):
                yield chunk
        yield suffix

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(prefix) + path.stat().st_size + len(suffix)),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base_url.rstrip("/")
        + "/transcribe?format="
        + output_format
        + "&diarization="
        + str(diarization).lower()
        + "&include_audio="
        + str(include_audio).lower(),
        data=body(),
        headers=headers,
        method="POST",
    )
    # This is a socket inactivity timeout, not an overall transcription deadline.
    with urllib.request.urlopen(request, timeout=60) as response:
        yield from iter_events(response, output_format)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--format", choices=("sse", "jsonl"), default="sse")
    parser.add_argument("--diarization", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--include-audio", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()
    try:
        for event in transcribe_events(
            args.audio,
            args.url,
            args.format,
            os.getenv("API_TOKEN", ""),
            diarization=args.diarization,
            include_audio=args.include_audio,
        ):
            print(json.dumps(event, ensure_ascii=False), flush=True)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
