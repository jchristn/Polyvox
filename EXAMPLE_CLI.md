# CLI examples

Install the native SDK, model files, FFmpeg, and Python environment using your
[OS guide](README.md). Unset `API_MODE` for CLI operation.

```bash
uv run --no-sync polyvox --doctor
uv run --no-sync polyvox --input recording.wav \
  --output-json output/transcript.json --output-txt output/transcript.txt \
  --diarize --include-audio
```

`python transcriber.py` is an equivalent entry point. Both output paths are
required and must differ from each other and the input. Output is staged before
replacement; individual replacements are atomic, but the pair is not a
transaction. JSON contains final segments and metadata; text contains timestamped
speaker lines. Audio is embedded only in JSON.

Use `--no-diarize` and `--no-include-audio` to override enabled environment
defaults. Change `--model`, `--diarization-model`, `--runtime-dir`, or `--device`
as appropriate. `--doctor` checks local prerequisites without loading models.
Provider, language, limits, and recovery settings use environment variables;
see [LIBRARY.md](LIBRARY.md) and [REST_API.md](REST_API.md).

```bash
uv run --no-sync polyvox --device metal --runtime-dir .runtime/nemo \
  --model models/nemotron-en.gguf --input interview.wav \
  --output-json output/interview.json --output-txt output/interview.txt --diarize
```

Download `nemotron-en` separately for this English-only example. For incremental
consumption, use the Python library or streaming HTTP API. CLI file outputs are
written after processing completes.
