"""Stable output and atomic replacement of individual files."""

import json
import os
import tempfile
from pathlib import Path


def format_transcript(segments: list[dict]) -> str:
    return "\n".join(
        f"[{s.get('start', 0)}-{s.get('end', 0)} {s.get('speaker', 'UNKNOWN')}] "
        f"{s.get('text', '').strip()}"
        for s in segments
    )


def write_output(result: dict, json_path: str, txt_path: str):
    paths = [Path(json_path).resolve(), Path(txt_path).resolve()]
    if paths[0] == paths[1]:
        raise ValueError("JSON and text output paths must differ")
    payloads = [
        json.dumps(result, indent=2, ensure_ascii=False),
        format_transcript(result["segments"]),
    ]
    staged = []
    try:
        for path, payload in zip(paths, payloads, strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as file:
                staged.append(Path(file.name))
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
        for temporary, path in zip(staged, paths, strict=True):
            os.replace(temporary, path)
    finally:
        for path in staged:
            path.unlink(missing_ok=True)
