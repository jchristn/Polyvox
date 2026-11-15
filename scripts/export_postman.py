#!/usr/bin/env python3
"""Generate drag-and-drop Postman v2.1 JSON from maintained Polyvox requests/docs."""

import argparse
import copy
import json
import uuid
from pathlib import Path
from urllib.parse import parse_qsl

import yaml

ROOT = Path(__file__).resolve().parents[1]
POSTMAN = ROOT / "postman"
SOURCE = POSTMAN / "collections/Polyvox"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
VARIABLES = [
    ("base_url", "http://127.0.0.1:8000", "Polyvox service origin, without a trailing slash."),
    ("api_token", "", "Service bearer token; leave empty when API_TOKEN is not configured."),
    (
        "audio_file",
        "tests/fixtures/jfk.wav",
        "Your audio/video file, relative to Postman's working directory.",
    ),
    ("output_format", "json", "Configured request output: text, json, jsonl, or sse."),
    ("diarization", "true", "Enable session-local speaker labels in editable requests."),
    (
        "include_audio",
        "false",
        "Include base64 WAV clips in structured output; text requires false.",
    ),
    ("fixture_audio_file", "tests/fixtures/jfk.wav", "Known speech fixture for acceptance tests."),
    ("invalid_audio_file", "openapi.yaml", "Intentionally invalid media file for error tests."),
    (
        "expected_text",
        "country",
        "Word expected in the acceptance fixture; not used for your audio.",
    ),
    ("expected_language_prefix", "en", "Expected acceptance-fixture language prefix, such as en."),
]

INTERACTIVE_TEST = r"""
pm.test("HTTP 200", () => pm.response.to.have.status(200));
pm.test("Complete, finalized output", () => {
  const contentType = pm.response.headers.get("Content-Type") || "";
  const text = pm.response.text();
  let segments, metadata;
  if (contentType.includes("application/json")) {
    const body = pm.response.json();
    segments = body.segments;
    metadata = body.metadata;
    pm.expect(body.segment_count).to.eql(segments.length);
  } else if (contentType.includes("text/event-stream") ||
             contentType.includes("application/x-ndjson")) {
    const sse = contentType.includes("text/event-stream");
    const events = text.split(/\r?\n/).filter(l => sse ? l.startsWith("data: ") : l.trim())
      .map(l => JSON.parse(sse ? l.slice(6) : l));
    const complete = events[events.length - 1];
    pm.expect(complete.type).to.eql("complete");
    pm.expect(events.some(e => e.type === "error")).to.eql(false);
    const emitted = events.filter(e => e.type === "segment");
    emitted.forEach((e, i) => {
      pm.expect(e.id).to.eql(i);
      pm.expect(e.final).to.eql(true);
    });
    segments = emitted.map(e => e.segment);
    metadata = complete.metadata;
    pm.expect(complete.segment_count).to.eql(segments.length);
  } else {
    pm.expect(contentType).to.include("text/plain");
    pm.expect(text).to.match(/# complete\n$/);
    pm.expect(text).not.to.include("# error ");
    return;
  }
  pm.expect(metadata.single_pass).to.eql(true);
  segments.forEach(s => {
    pm.expect(s.start).to.be.at.least(0);
    pm.expect(s.end).to.be.at.least(s.start);
    pm.expect(s.len).to.be.closeTo(s.end - s.start, 0.000001);
    pm.expect(s.text).to.be.a("string");
    pm.expect(s.speaker).to.be.a("string");
    if (!metadata.diarization) pm.expect(s.speaker).to.eql("UNKNOWN");
    if (metadata.include_audio) {
      pm.expect(s.audio.encoding).to.eql("base64");
      pm.expect(s.audio.content_type).to.eql("audio/wav");
      pm.expect(s.audio.sample_rate).to.eql(16000);
      pm.expect(s.audio.channels).to.eql(1);
      pm.expect(s.audio.data).to.match(/^UklGR/);
    } else pm.expect(s).not.to.have.property("audio");
  });
});
""".strip()


def identity(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/jchristn/Polyvox/" + name))


def event(code, listen="test"):
    return {"listen": listen, "script": {"type": "text/javascript", "exec": code.splitlines()}}


def auth(source):
    kind = source["type"]
    result = {"type": kind}
    if "credentials" in source:
        result[kind] = [{**v, "type": "string"} for v in source["credentials"]]
    return result


def url(raw, query=None):
    path = raw.split("?", 1)[0].removeprefix("{{base_url}}/")
    if query is None:
        query = [{"key": k, "value": v} for k, v in parse_qsl(raw.partition("?")[2])]
    return {
        "raw": raw,
        "host": ["{{base_url}}"],
        "path": path.split("/") if path else [],
        "query": query,
    }


def convert(path):
    source = yaml.safe_load(path.read_text())
    name = source.get("name", path.stem.removesuffix(".request").replace("-", " ").title())
    request = {
        "method": source["method"],
        "header": [],
        "url": url(source["url"], source.get("queryParams")),
    }
    if "auth" in source:
        request["auth"] = auth(source["auth"])
    if "body" in source:
        body = source["body"]
        form = copy.deepcopy(body["content"])
        for field in form:
            if field.get("type") == "file":
                field["src"] = (
                    "{{invalid_audio_file}}"
                    if field["src"] == "openapi.yaml"
                    else "{{fixture_audio_file}}"
                )
                field["description"] = (
                    "Local file path resolved through the selected environment and working "
                    "directory."
                )
        request["body"] = {"mode": "formdata", "formdata": form}
    scripts = []
    for script in source.get("scripts", []):
        code = script["code"].replace(
            'to.include("country")',
            'to.include(String(pm.variables.get("expected_text")).toLowerCase())',
        )
        code = code.replace(
            "/^en(?:-|$)/",
            'new RegExp("^" + pm.variables.get("expected_language_prefix") + "(?:-|$)")',
        )
        scripts.append(event(code, "test" if script["type"] == "afterResponse" else "prerequest"))
    request["description"] = acceptance_description(path.stem.removesuffix(".request"), request)
    return {
        "id": identity(path.name),
        "name": name,
        "request": request,
        "event": scripts,
        "response": [],
    }


def acceptance_description(slug, request):
    details = {
        "liveness": "Public process liveness. Does not initialize models; expect status ok.",
        "liveness-head": "Public HEAD liveness. Expect 200 and an empty body.",
        "readiness": (
            "Public prerequisites/circuit check. Expect ready; this is not an inference benchmark."
        ),
        "metrics": (
            "Authenticated job/circuit counters. Reports streaming-engine and the "
            "configured device."
        ),
        "authentication-policy": (
            "Deliberately omits authentication. Expect 401 when api_token is "
            "populated, otherwise 200. Match this variable to the server's "
            "API_TOKEN policy."
        ),
        "missing-file": "Deliberately omits the multipart file. Expect 400.",
        "invalid-format": "Uses an unsupported format. Expect 400 before inference.",
        "invalid-media": (
            "Uploads invalid_audio_file, which must not be audio/video. Full JSON "
            "processing should return HTTP 422."
        ),
        "invalid-media-stream": (
            "Uploads invalid_audio_file using SSE. Expect HTTP 200 followed by "
            "terminal invalid_media/422, and no complete event."
        ),
        "clear-models": (
            "Confirm models are released while idle. Each job releases its own "
            "models; active work returns 503. Run against an idle test instance."
        ),
    }
    detail = details.get(
        slug,
        (
            "Transcribe fixture_audio_file and verify the output contract, "
            "recognized fixture text, segment durations, and successful completion."
            " Stream cases require unique final IDs and the requested speaker/audio"
            " behavior."
        ),
    )
    return (
        "### "
        + slug.replace("-", " ").title()
        + "\n\n"
        + detail
        + "\n\n"
        + (
            (
                "This fixed acceptance case preserves its explicit option values. It "
                "uses the environment's base_url, api_token, and fixture/error-file "
                "variables. "
            )
            + (
                "Use **Transcribe your audio** for requests controlled by "
                "output_format, diarization, and include_audio. "
            )
            + "Requests run real inference; run sequentially on a test instance."
        )
    )


def example_response(request, fmt, include_audio=False):
    sample = json.loads((POSTMAN / "examples/segment.json").read_text())
    segment = sample["segment"]
    if not include_audio:
        segment.pop("audio", None)
    metadata = sample["metadata"] | {"include_audio": include_audio}
    transcript = {
        "segments": [segment],
        "segment_count": 1,
        "language": sample["language"],
        "metadata": metadata,
    }
    request_id = "0123456789abcdef0123456789abcdef"
    events = [
        {"type": "started", "request_id": request_id},
        {
            "type": "attempt",
            "request_id": request_id,
            "attempt": 1,
            "reset": True,
            "device": "cpu",
            "requested_device": "cpu",
        },
        {
            "type": "segment",
            "request_id": request_id,
            "attempt": 1,
            "id": 0,
            "final": True,
            "segment": segment,
        },
        {
            "type": "complete",
            "request_id": request_id,
            "segment_count": 1,
            "language": sample["language"],
            "metadata": metadata,
        },
    ]
    if fmt == "json":
        body, content_type = json.dumps(transcript, indent=2), "application/json"
    elif fmt == "text":
        body = (
            f"[{segment['start']}-{segment['end']} {segment['speaker']}] "
            f"{segment['text']}\n# complete\n"
        )
        content_type = "text/plain; charset=utf-8"
    elif fmt == "sse":
        body = "".join(
            f"event: {e['type']}\ndata: {json.dumps(e, separators=(',', ':'))}\n\n" for e in events
        )
        content_type = "text/event-stream"
    else:
        body = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
        content_type = "application/x-ndjson"
    original = json.loads(
        json.dumps(request)
        .replace("{{output_format}}", fmt)
        .replace("{{diarization}}", "true")
        .replace("{{include_audio}}", str(include_audio).lower())
    )
    return {
        "name": f"200 / {fmt.upper()} / single-segment excerpt"
        + (" with WAV audio" if include_audio else ""),
        "originalRequest": original,
        "status": "OK",
        "code": 200,
        "header": [
            {"key": "Content-Type", "value": content_type},
            {"key": "X-Request-ID", "value": request_id},
            {"key": "Cache-Control", "value": "no-store"},
        ],
        "cookie": [],
        "body": body,
    }


def interactive(name, fmt, *, body_options=False):
    options = [
        {
            "key": "format",
            "value": fmt,
            "description": "text, json, jsonl, or sse; text cannot include audio.",
        },
        {
            "key": "diarization",
            "value": "{{diarization}}",
            "description": "Enable speaker labels; false emits UNKNOWN.",
        },
        {
            "key": "include_audio",
            "value": "false" if fmt == "text" else "{{include_audio}}",
            "description": "Base64 PCM16 WAV clips in structured segments.",
        },
    ]
    raw = "{{base_url}}/transcribe"
    if not body_options:
        raw += "?" + "&".join(f"{v['key']}={v['value']}" for v in options)
    request = {
        "method": "POST",
        "header": [],
        "url": url(raw, [] if body_options else options),
        "body": {
            "mode": "formdata",
            "formdata": [
                {
                    "key": "file",
                    "type": "file",
                    "src": "{{audio_file}}",
                    "description": (
                        "Your local file; configure audio_file or select one with the file picker."
                    ),
                }
            ],
        },
        "description": "### "
        + name
        + "\n\nUpload `{{audio_file}}` with request-scoped options from the selected environment. "
        + (
            "Options are multipart text fields in this example; do not repeat them in the query. "
            if body_options
            else "Options are query parameters; do not repeat them in the body. "
        )
        + (
            "Set `{{diarization}}` and `{{include_audio}}` independently. The text "
            "request fixes audio to false. "
        )
        + (
            "The configured-output request uses `{{output_format}}`; named format "
            "requests keep their advertised format. "
        )
        + (
            "All structured segments have start/end/len, text, and speaker; "
            "optional audio contains a complete base64 WAV. "
        )
        + "Streams succeed only with complete (or # complete for text), even after HTTP 200. "
        + (
            "Tests validate the contract without assuming your audio contains "
            "English or particular words. "
        )
        + (
            "Saved responses are shortened, single-segment excerpts from the "
            "bundled fixture; counts reflect the excerpt."
        ),
    }
    if body_options:
        request["body"]["formdata"] += [{**v, "type": "text"} for v in options]
    example_format = "json" if fmt.startswith("{{") else fmt
    responses = [example_response(request, example_format)]
    if example_format == "json":
        responses.append(example_response(request, "json", include_audio=True))
    return {
        "id": identity(name),
        "name": name,
        "request": request,
        "event": [event(INTERACTIVE_TEST)],
        "response": responses,
    }


def build():
    definition = yaml.safe_load((SOURCE / ".resources/definition.yaml").read_text())
    paths = sorted(
        SOURCE.glob("*.request.yaml"),
        key=lambda p: (yaml.safe_load(p.read_text())["order"], p.name),
    )
    acceptance = [convert(p) for p in paths]
    health = [copy.deepcopy(item) for item in acceptance[:4]]
    for item in health:
        item["id"] = identity("health/" + item["name"])
    collection = {
        "info": {
            "_postman_id": identity("collection"),
            "name": "Polyvox API v1.0.0",
            "description": (POSTMAN / "DOCUMENTATION.md").read_text(),
            "schema": SCHEMA,
        },
        "auth": auth(definition["auth"]),
        "variable": [
            {"key": k, "value": v, "type": "string", "description": d} for k, v, d in VARIABLES
        ],
        "event": [event(s["code"]) for s in definition["scripts"]],
        "item": [
            {
                "name": "Service status",
                "description": (
                    "Start with Readiness. Liveness and readiness are public; metrics "
                    "inherits bearer authentication."
                ),
                "item": health,
            },
            {
                "name": "Transcribe your audio",
                "description": (
                    "Editable requests using your environment variables. Test scripts work "
                    "with arbitrary audio; saved responses illustrate finalized segments "
                    "and optional WAV clips."
                ),
                "item": [
                    interactive("Configured output (query options)", "{{output_format}}"),
                    interactive("Full JSON (multipart options)", "json", body_options=True),
                    interactive("Text captions", "text"),
                    interactive("SSE events", "sse"),
                    interactive("JSONL events", "jsonl"),
                ],
            },
            {
                "name": "Acceptance suite",
                "description": (
                    "21 fixed scenarios. Run sequentially against an idle test server using"
                    " the known fixture. Error responses are intentional. This folder calls"
                    " /clear-models and performs real inference."
                ),
                "item": acceptance,
            },
        ],
    }
    environment = {
        "id": identity("environment/local"),
        "name": "Polyvox - Local",
        "values": [
            {
                "key": k,
                "value": v,
                "type": "secret" if k == "api_token" else "default",
                "enabled": True,
            }
            for k, v, _ in VARIABLES
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "Polyvox 1.0.0",
    }
    return {
        "Polyvox.postman_collection.json": collection,
        "Polyvox.local.postman_environment.json": environment,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail when checked-in exports are stale"
    )
    args = parser.parse_args()
    for name, artifact in build().items():
        path = POSTMAN / name
        content = json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise SystemExit(
                    f"Stale Postman export: run python scripts/export_postman.py ({name})"
                )
        else:
            path.write_text(content)
            print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
