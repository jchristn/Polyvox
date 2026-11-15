"""CLI and production HTTP entry points."""

import argparse
import json
import logging
import os
import signal
from dataclasses import replace
from pathlib import Path

from .config import DEVICES, Settings, boolean
from .errors import TranscriberError
from .output import write_output
from .service import TranscriptionService


def parser():
    result = argparse.ArgumentParser(description="Streaming transcription and diarization")
    result.add_argument("--input")
    result.add_argument("--output-json")
    result.add_argument("--output-txt")
    result.add_argument("--device", choices=DEVICES)
    result.add_argument("--model", dest="model_path")
    result.add_argument("--diarize", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--include-audio", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--diarization-model")
    result.add_argument("--runtime-dir")
    result.add_argument("--doctor", action="store_true", help="Check local prerequisites")
    return result


def main(argv=None):
    logging.addLevelName(logging.WARNING, "WARN")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings.from_env()
        if boolean(os.environ.get("API_MODE", "false")):
            from waitress import serve

            from .api import create_app
            from .process import shutdown

            def stop(signum, frame):
                shutdown()
                raise SystemExit(0)

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            # Start even with a missing model so liveness and diagnostic readiness work.
            app = create_app(settings)
            try:
                serve(
                    app,
                    host=os.environ.get("HOST", "127.0.0.1"),
                    port=int(os.environ.get("PORT", "8000")),
                    threads=max(4, settings.max_pending + 3),
                    max_request_body_size=settings.max_upload_bytes,
                    connection_limit=64,
                )
            finally:
                shutdown()
            return 0
        args = parser().parse_args(argv)
        updates = {
            name: getattr(args, name)
            for name in (
                "device",
                "model_path",
                "diarization_model",
                "runtime_dir",
                "include_audio",
            )
            if getattr(args, name) is not None
        }
        if args.diarize is not None:
            updates["diarization"] = args.diarize
        settings = replace(settings, **updates)
        settings.check()
        if args.doctor:
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "device": settings.device,
                        "scope": "local-prerequisites; run hardware tests to verify acceleration",
                    }
                )
            )
            return 0
        if not all((args.input, args.output_json, args.output_txt)):
            raise ValueError("--input, --output-json, and --output-txt are required")
        source = Path(args.input)
        if not source.is_file():
            raise ValueError(f"Input is not a file: {source}")
        if source.stat().st_size > settings.max_upload_bytes:
            raise ValueError("Input exceeds MAX_UPLOAD_BYTES")
        targets = [Path(args.output_json).resolve(), Path(args.output_txt).resolve()]
        if source.resolve() in targets or targets[0] == targets[1]:
            raise ValueError("Input, JSON output, and text output must be distinct files")
        result = TranscriptionService(settings).transcribe(source)
        write_output(result, args.output_json, args.output_txt)
        return 0
    except (TranscriberError, ValueError, OSError) as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        return 130
