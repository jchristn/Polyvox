from pathlib import Path
from urllib.parse import urlsplit

import yaml
from openapi_spec_validator import validate

from polyvox.api import create_app


def test_openapi_is_valid_and_covers_routes(settings):
    spec = yaml.safe_load(Path("openapi.yaml").read_text())
    validate(spec)
    app = create_app(settings)
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        assert rule.rule in spec["paths"]
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert method.lower() in spec["paths"][rule.rule]


def test_postman_requests_cover_openapi_operations():
    spec = yaml.safe_load(Path("openapi.yaml").read_text())
    expected = {
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        for method in methods
        if method in {"get", "head", "post", "put", "patch", "delete", "options"}
    }
    covered = set()
    for path in Path("postman/collections/Polyvox").rglob("*.request.yaml"):
        request = yaml.safe_load(path.read_text())
        url = request["url"].replace("{{base_url}}", "http://localhost")
        operation = request["method"], urlsplit(url).path
        assert operation in expected, f"Undocumented operation in {path}"
        covered.add(operation)
    assert covered == expected, f"Missing Postman requests: {expected - covered}"


def exported_items(collection):
    for item in collection["item"]:
        if "item" in item:
            yield from exported_items(item)
        else:
            yield item


def test_postman_export_does_not_depend_on_filesystem_order(monkeypatch):
    from scripts.export_postman import SOURCE, build

    expected = build()
    paths = list(SOURCE.glob("*.request.yaml"))
    glob = Path.glob
    monkeypatch.setattr(
        Path,
        "glob",
        lambda self, pattern: reversed(paths) if self == SOURCE else glob(self, pattern),
    )
    assert build() == expected


def test_importable_postman_exports_are_current_and_parameterized():
    import json
    import re

    from scripts.export_postman import POSTMAN, build

    artifacts = build()
    for name, artifact in artifacts.items():
        assert json.loads((POSTMAN / name).read_text()) == artifact
    collection = artifacts["Polyvox.postman_collection.json"]
    environment = artifacts["Polyvox.local.postman_environment.json"]
    assert collection["info"]["name"] == "Polyvox API v1.0.0"
    assert "/v2.1.0/" in collection["info"]["schema"]
    assert environment["_postman_variable_scope"] == "environment"
    variables = {v["key"] for v in collection["variable"]}
    references = set(re.findall(r"\{\{([a-z_]+)\}\}", json.dumps(collection)))
    assert references <= variables
    assert {v["key"] for v in environment["values"]} == variables
    token = next(v for v in environment["values"] if v["key"] == "api_token")
    assert token["type"] == "secret" and token["value"] == ""
    items = list(exported_items(collection))
    assert len(items) == 30
    assert len({item["id"] for item in items}) == len(items)
    assert all(item["request"]["description"] for item in items)
    assert collection["auth"]["bearer"][0]["value"] == "{{api_token}}"
    for item in items:
        for field in item["request"].get("body", {}).get("formdata", []):
            if field["type"] == "file":
                assert field["src"].startswith("{{")


def test_importable_postman_covers_routes_and_preserves_acceptance_cases():
    import json

    collection = json.loads(Path("postman/Polyvox.postman_collection.json").read_text())
    spec = yaml.safe_load(Path("openapi.yaml").read_text())
    expected = {
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        for method in methods
        if method in {"get", "head", "post", "put", "patch", "delete", "options"}
    }
    covered = set()
    for item in exported_items(collection):
        request = item["request"]
        path = "/" + "/".join(request["url"]["path"])
        operation = request["method"], path
        assert operation in expected
        covered.add(operation)
    assert covered == expected
    suite = next(folder for folder in collection["item"] if folder["name"] == "Acceptance suite")
    assert len(suite["item"]) == len(
        list(Path("postman/collections/Polyvox").glob("*.request.yaml"))
    )


def test_saved_postman_examples_match_openapi_and_audio_interval():
    import base64
    import io
    import json
    import wave

    import pytest
    from jsonschema import Draft202012Validator

    collection = json.loads(Path("postman/Polyvox.postman_collection.json").read_text())
    spec = yaml.safe_load(Path("openapi.yaml").read_text())
    seen = set()
    for item in exported_items(collection):
        for response in item["response"]:
            content_type = next(
                h["value"] for h in response["header"] if h["key"] == "Content-Type"
            )
            seen.add(content_type)
            body = response["body"]
            if content_type == "application/json":
                payload = json.loads(body)
                schema = {
                    "$ref": "#/components/schemas/Transcript",
                    "components": spec["components"],
                }
                Draft202012Validator(schema).validate(payload)
                assert payload["segment_count"] == len(payload["segments"])
                for segment in payload["segments"]:
                    if "audio" in segment:
                        data = base64.b64decode(segment["audio"]["data"], validate=True)
                        with wave.open(io.BytesIO(data)) as clip:
                            assert clip.getnframes() / clip.getframerate() == pytest.approx(
                                segment["len"]
                            )
            elif content_type in {"text/event-stream", "application/x-ndjson"}:
                events = [
                    json.loads(line[6:] if content_type == "text/event-stream" else line)
                    for line in body.splitlines()
                    if line.startswith("data: ")
                    or (content_type == "application/x-ndjson" and line)
                ]
                validator = Draft202012Validator(
                    {"$ref": "#/components/schemas/StreamEvent", "components": spec["components"]}
                )
                for event in events:
                    validator.validate(event)
                assert events[-1]["type"] == "complete"
            else:
                assert body.endswith("# complete\n")
    assert seen == {
        "application/json",
        "text/event-stream",
        "application/x-ndjson",
        "text/plain; charset=utf-8",
    }
