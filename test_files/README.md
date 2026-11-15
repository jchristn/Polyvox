# Polyvox test audio

`sample.wav` is an approximately 11-second English speech recording in mono,
16 kHz, signed 16-bit PCM WAV format. It contains John F. Kennedy's “ask not”
passage. Expect words such as “ask” and “country”; exact punctuation may vary.
This single-speaker recording exercises transcription, speaker labeling, and
segment audio output, but does not test switching between multiple speakers.

The speech is a US federal government work. This is the same sample used by the
repository's automated tests, sourced from
[whisper.cpp v1.9.5](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/samples/jfk.wav).

```bash
curl -N -F 'file=@test_files/sample.wav' \
  'http://127.0.0.1:8000/transcribe?format=sse&diarization=true&include_audio=true'
```

In the Polyvox Postman environment, set `audio_file` to `test_files/sample.wav`
and set Postman's working directory to the project root. Alternatively, select
this file through **Body > form-data > file**.
