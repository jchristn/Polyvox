"""Small HTTP adapter; resource and recovery policy lives in the service."""

import hmac
import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .config import Settings, boolean
from .errors import BackendFailure, Busy, ConfigurationError, TranscriberError
from .service import TranscriptionService
from .streaming import stream_response

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, service=None) -> Flask:
    settings = settings or Settings.from_env()
    service = service or TranscriptionService(settings)
    app = Flask(__name__)
    app.json.sort_keys = False
    app.config.update(
        MAX_CONTENT_LENGTH=settings.max_upload_bytes,
        MAX_FORM_MEMORY_SIZE=512 * 1024,
        MAX_FORM_PARTS=8,
    )
    app.extensions["transcription_service"] = service
    uploads = threading.BoundedSemaphore(1 + settings.max_pending)
    token = os.environ.get("API_TOKEN", "")

    @app.before_request
    def authenticate():
        g.request_id = uuid.uuid4().hex
        if (
            token
            and request.path not in ("/", "/ready")
            and not hmac.compare_digest(
                request.headers.get("Authorization", "").encode(), f"Bearer {token}".encode()
            )
        ):
            return jsonify(error="unauthorized", request_id=g.request_id), 401
        return None

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(TranscriberError)
    def service_error(exc):
        logger.warning("Request %s failed: %s", g.request_id, exc, exc_info=True)
        detail = str(exc)
        if isinstance(exc, (BackendFailure, ConfigurationError)):
            detail = "Backend unavailable; inspect service logs and configuration"
        response = jsonify(error=exc.code, detail=detail, request_id=g.request_id)
        response.status_code = exc.status
        if exc.status == 503:
            response.headers["Retry-After"] = str(max(1, int(settings.cooldown)))
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name, request_id=g.request_id), exc.code

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        logger.exception("Request %s failed unexpectedly", g.request_id)
        return jsonify(error="internal_error", request_id=g.request_id), 500

    @app.get("/")
    def health():
        return jsonify(status="ok")

    @app.get("/ready")
    def ready():
        service.check_ready()
        return jsonify(status="ready", scope="configuration-and-circuit")

    @app.get("/metrics")
    def metrics():
        return jsonify(service.snapshot())

    @app.post("/clear-models")
    def clear_models():
        service.clear_models()
        return jsonify(status="ok", message="No cached models; each job releases its models")

    @app.post("/transcribe")
    def transcribe():
        if not uploads.acquire(blocking=False):
            raise Busy("Upload capacity reached; retry later")
        temp = None
        handed_off = False
        cleaned = False

        def cleanup():
            nonlocal cleaned
            if not cleaned:
                cleaned = True
                try:
                    if temp is not None:
                        temp.cleanup()
                finally:
                    uploads.release()

        try:

            def option(name, default):
                values = request.args.getlist(name) + request.form.getlist(name)
                if len(values) > 1:
                    raise ValueError(f"Specify {name} once, in query or multipart body")
                return values[0] if values else default

            try:
                output_format = option("format", "text")
                if output_format not in ("text", "json", "sse", "jsonl"):
                    raise ValueError("format must be text, json, sse, or jsonl")
                options = {
                    "diarization": boolean(option("diarization", str(settings.diarization))),
                    "include_audio": boolean(option("include_audio", str(settings.include_audio))),
                }
                if output_format == "text" and options["include_audio"]:
                    raise ValueError("include_audio requires json, jsonl, or sse")
            except (ValueError, ConfigurationError) as exc:
                return jsonify(error=str(exc)), 400
            file = request.files.get("file")
            if file is None or not file.filename:
                return jsonify(error="Provide a file in the multipart 'file' field"), 400
            service.check_ready(service.options(**options))
            temp = tempfile.TemporaryDirectory(prefix="polyvox-upload-", dir=settings.temp_dir)
            # Never use the client filename as a path or argument.
            source = Path(temp.name) / "upload"
            file.save(source)
            if not source.stat().st_size:
                return jsonify(error="File is empty"), 400
            if output_format in ("text", "sse", "jsonl"):
                response = stream_response(
                    service, source, cleanup, g.request_id, output_format, **options
                )
                handed_off = True
                return response
            return jsonify(service.transcribe(source, **options))
        finally:
            if not handed_off:
                cleanup()

    return app
