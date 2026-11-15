#!/usr/bin/env python3
"""Exercise the built image's real HTTP server and native inference as a non-root user."""

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="jchristn77/polyvox-server:v1.0.0")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    name = "transcriber-test-" + uuid.uuid4().hex[:10]
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::8000",
            "-e",
            "API_MODE=true",
            "-e",
            "MODEL_PATH=/models/nemotron-asr.gguf",
            "-e",
            "DIARIZATION_MODEL=/models/nemotron-diar.gguf",
            "-v",
            f"{root / 'models'}:/models:ro",
            args.image,
        ],
        check=True,
        capture_output=True,
    )
    try:
        port = (
            subprocess.check_output(["docker", "port", name, "8000/tcp"], text=True)
            .strip()
            .rsplit(":", 1)[1]
        )
        base = f"http://127.0.0.1:{port}"
        for attempt in range(60):
            try:
                with urllib.request.urlopen(base + "/ready", timeout=3) as response:
                    assert response.status == 200
                break
            except (OSError, urllib.error.URLError):
                if attempt == 59:
                    raise
                time.sleep(1)

        def upload(data, output_format="json"):
            boundary = "TranscriberTestBoundary"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="test.wav"\r\nContent-Type: audio/wav\r\n\r\n'
            ).encode()
            body += data + f"\r\n--{boundary}--\r\n".encode()
            request = urllib.request.Request(
                base + "/transcribe?diarization=true&include_audio=true&format=" + output_format,
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            return urllib.request.urlopen(request, timeout=300)

        try:
            upload(b"broken audio")
        except urllib.error.HTTPError as exc:
            assert exc.code == 422, exc.read()
        else:
            raise AssertionError("Invalid audio was accepted")
        with upload((root / "tests/fixtures/jfk.wav").read_bytes()) as response:
            result = json.load(response)
        text = " ".join(segment["text"] for segment in result["segments"]).lower()
        assert "country" in text and "ask" in text, result
        assert result["metadata"]["device"] == "cpu"
        assert all(abs(s["len"] - (s["end"] - s["start"])) < 1e-6 for s in result["segments"])
        for output_format in ("sse", "jsonl"):
            events = []
            with upload((root / "tests/fixtures/jfk.wav").read_bytes(), output_format) as response:
                for raw in response:
                    line = raw.decode("utf-8").strip()
                    if output_format == "sse":
                        if not line.startswith("data: "):
                            continue
                        line = line[6:]
                    if line:
                        events.append(json.loads(line))
            assert events[-1]["type"] == "complete", events
            assert events[-1]["metadata"]["device"] == "cpu"
            segments = {}
            for event in events:
                if event["type"] == "attempt":
                    segments.clear()
                if event["type"] == "segment":
                    segments[event["id"]] = event
            final = [segments[i] for i in range(events[-1]["segment_count"])]
            assert all(event["final"] for event in final)
            assert len([e for e in events if e["type"] == "segment"]) == len(final)
            assert any(e["segment"]["speaker"].startswith("SPEAKER_") for e in final)
            assert all(e["segment"]["audio"]["data"].startswith("UklGR") for e in final)
            assert "country" in " ".join(e["segment"]["text"] for e in final).lower()
            assert all(
                abs(e["segment"]["len"] - (e["segment"]["end"] - e["segment"]["start"])) < 1e-6
                for e in final
            )
        uid = subprocess.check_output(["docker", "exec", name, "id", "-u"], text=True).strip()
        assert uid != "0"
        print(
            f"PASS: {args.image}: readiness, invalid-media recovery, "
            f"JSON/SSE/JSONL transcription, non-root uid={uid}"
        )
    except BaseException:
        subprocess.run(["docker", "logs", name], check=False)
        raise
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    main()
