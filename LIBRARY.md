# Python library and model adapters

Install with `uv sync --locked` for development, or install the built wheel.
FFmpeg/FFprobe, a matching native SDK, and model files are separate prerequisites
for file transcription. Python 3.12–3.14 is supported.

## Files and streamed events

```python
from polyvox import Settings, Transcriber

settings = Settings(
    runtime_dir=".runtime/nemo",
    model_path="models/nemotron-asr.gguf",
    diarization_model="models/nemotron-diar.gguf",
    device="cpu",
)
service = Transcriber(settings)
result = service.transcribe("recording.wav", diarization=True, include_audio=True)
for segment in result["segments"]:
    print(segment["start"], segment["end"], segment["len"], segment["text"])

with service.stream("recording.wav", diarization=True, include_audio=False) as events:
    for event in events:
        if event["type"] == "segment":
            print(event["segment"])
        elif event["type"] == "error":
            raise RuntimeError(event)
```

`Transcriber()` reads environment settings. Explicit `Settings()` uses dataclass
defaults; use `Settings.from_env()` when environment overrides are wanted.
Per-call options must be Python booleans; omitted options inherit settings.
`transcribe()` returns a complete dictionary or raises a `TranscriberError`.
`stream()` uses the [API event contract](REST_API.md); errors during execution
are terminal events. Use its context manager, especially when stopping early.
Closing cancels the isolated worker. Require `complete` before accepting a job
as successful. One service instance runs one job at a time with bounded admission.

## Live PCM input

```python
import wave
from polyvox import Engine, Settings

settings = Settings(diarization=True, include_audio=True)
with wave.open("mono-16khz-pcm16.wav", "rb") as source, Engine(settings) as engine:
    assert (source.getnchannels(), source.getframerate(), source.getsampwidth()) == (1, 16000, 2)
    while chunk := source.readframes(2560):  # 160 ms; a microphone can supply these bytes
        for segment in engine.push_pcm16(chunk):
            print(segment)
    for segment in engine.finish():
        print(segment)
    print(engine.metadata)
```

Input is signed PCM16 little-endian, mono, 16 kHz, at most one second per push.
Do not include a WAV header. Calls are sequential for one session. Each model
loads once and retains state between pushes; both receive the same float32 PCM
chunk concurrently. ASR supplies committed words on the session clock. The
engine waits for the diarizer's stable watermark, assigns words by speaker
overlap, and emits each segment once. Finishing flushes both models. No audio
replay is needed for diarization. Session-wide speaker IDs are retained.

`Engine` runs in process. Its deadlines are checked between native calls, so
hard cancellation requires process isolation; the file service supplies that.
Always close it. It returns segment dictionaries, without HTTP/event envelopes.
Optional clips are drawn from a temporary PCM spool and contain mixed source
audio, not separated voices. `max_duration` and `max_audio_bytes` bound input
and emitted base64 audio; disk requirements still depend on recording duration.

## Change a compatible model

```bash
python scripts/download_model.py nemotron-en
export MODEL_PATH=models/nemotron-en.gguf
```

Or set `Settings(model_path="...", diarization_model="...")` independently.
ASR replacements must use GGUF architectures supported by the installed SDK.
The built-in diarizer requires V3 models with 10 ms output cadence; other models
need an adapter that implements their stability rules. In either case, an arbitrary model file is not interchangeable.

Default choices:

| Role | Model | Pinned Q8 download size |
| --- | --- | --- |
| Multilingual ASR | [Nemotron 3.5 ASR Streaming 0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) | 741,548,352 bytes |
| English ASR alternative | [Nemotron Speech Streaming EN 0.6B](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b) | about 700 MB |
| Online diarization | [Nemotron 3 Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization) | 107,012,128 bytes |

The default ASR supports 32 locales out of the box; the model card lists another
eight requiring adaptation. Set `LANGUAGE` to a supported locale or `auto`.
Diarization supports up to eight speakers. Neither parameter count nor download
size establishes inference speed, accuracy, or peak memory; benchmark your audio.
Review the upstream model licenses for your deployment.

## Replace either provider

`polyvox.providers` exports `Recognizer`, `Diarizer`, `Word`, and `Turn`.
Install a trusted Python package with a factory taking `Settings` and returning
one of these protocols:

```python
# my_models.py in an installed package
from polyvox.providers import Word, Turn


def create_asr(settings):
    return MyStreamingRecognizer(settings.model_path, settings.device)


def create_diarizer(settings):
    return MyOnlineDiarizer(settings.diarization_model, settings.diarization_device)
```

The two application-defined classes implement these contracts:

| Provider | Required attributes and methods |
| --- | --- |
| Recognizer | `language: str`, `device: str`, `push(samples) -> list[Word]`, `finish() -> list[Word]`, `close()` |
| Diarizer | `device: str`, `stable_until: float`, `push(samples)`, `finish()`, `turns() -> list[Turn]`, `close()` |

Samples are `array('f')`, mono float32 at 16 kHz. Word and Turn times are absolute
seconds from the session start. Words must be finite, ordered, non-overlapping,
committed, and returned exactly once. Turn speaker names must remain stable
within a session. `stable_until` must never advance beyond the interval whose
labels will remain fixed; `turns()` must retain coverage for pending words.
At finish the provider must flush all results. `close()` must safely release
resources, including after partial initialization. Report the actual device.
Raise `ConfigurationError` for incompatible setup and `BackendFailure` for
retryable inference failure; do not silently switch devices.

```bash
export ASR_PROVIDER=my_models:create_asr
export DIARIZATION_PROVIDER=my_models:create_diarizer
```

These settings are administrator-controlled imports, never request parameters.
Install the package in the service environment so isolated workers can import it.
Model validation belongs in each custom factory. Either side can stay `nemo`
while the other is replaced. Low-level embedded use can instead inject callables:

```python
with Engine(settings, asr_factory=create_asr, diarizer_factory=create_diarizer) as engine:
    ...
```

An offline-only recognizer or diarizer cannot satisfy low-latency streaming by
renaming methods. It must implement committed incremental results and stable
speaker state, or explicitly delay its watermark until finish. Provider contract
and factory-swapping tests are in `tests/test_pipeline.py`.
