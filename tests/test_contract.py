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
