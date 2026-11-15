"""One job per process. Native failures cannot poison the HTTP process."""

import json
import logging
import sys
from pathlib import Path

from .config import Settings
from .errors import TranscriberError
from .pipeline import transcribe


def main():
    job_path, result_path = map(Path, sys.argv[1:])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    try:

        def emit(event):
            print("POLYVOX_EVENT\t" + json.dumps(event, ensure_ascii=True), flush=True)

        kwargs = {"emit": emit} if job.get("stream") else {}
        result = {
            "result": transcribe(
                Path(job["source"]), job_path.parent, Settings(**job["settings"]), **kwargs
            )
        }
    except TranscriberError as exc:
        logging.exception("Job failed")
        result = {"error": exc.code, "detail": str(exc)}
    except Exception:
        logging.exception("Unexpected job failure")
        result = {"error": "backend_failure", "detail": "Inference failed; inspect service logs"}
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
