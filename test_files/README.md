# Polyvox test audio

## Small speech clips

These mono clips are trimmed from **Open Speech Repository** recordings. WAV
files retain the source's 8 kHz, signed 16-bit PCM audio; the FLAC file is a
lossless encoding of a different sentence. They exercise input resampling,
different voices, and compressed audio decoding.

| File | Duration | Size (bytes) | Source interval (seconds) |
| --- | ---: | ---: | --- |
| [speech-us-female.wav](speech-us-female.wav) | 3.05 s | 48,844 | US female: 0.25–3.30 |
| [speech-us-male.wav](speech-us-male.wav) | 3.35 s | 53,644 | US male: 1.65–5.00 |
| [speech-uk-male.wav](speech-uk-male.wav) | 3.60 s | 57,644 | UK male: 1.10–4.70 |
| [speech-us-female.flac](speech-us-female.flac) | 2.75 s | 33,106 | US female: 4.05–6.80 |

The US female and UK male WAV clips contain “The birch canoe slid on the smooth
planks.” The US male WAV contains words such as “sockets,” “wall,” and “green.”
The FLAC clip contains “Glue the sheet to the dark blue background.” These are
[Harvard sentences](https://www.cs.columbia.edu/~hgs/audio/harvard.html).
Recognition, punctuation, and speaker IDs may vary; short segments may receive
an `UNKNOWN` speaker label. Each clip has one speaker; these are smoke-test
inputs, not a multi-speaker diarization benchmark.

Sources (retrieved November 15, 2026):

- [US female recording](https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0010_8k.wav)
- [US male recording](https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0030_8k.wav)
- [UK male recording](https://www.voiptroubleshooter.com/open_speech/british/OSR_uk_000_0020_8k.wav)

The repository's [American](https://www.voiptroubleshooter.com/open_speech/american.html)
and [British](https://www.voiptroubleshooter.com/open_speech/british.html) pages
permit copying, modification, and use in testing and development, with source
attribution to **Open Speech Repository**. These recordings retain those source
terms; the project's code license does not replace them.

## Original sample

`sample.wav` is an approximately 11-second English speech recording in mono,
16 kHz, signed 16-bit PCM WAV format. It contains John F. Kennedy's “ask not”
passage. Expect words such as “ask” and “country”; exact punctuation may vary.
This single-speaker recording exercises transcription, speaker labeling, and
segment audio output, but does not test switching between multiple speakers.

The speech is a US federal government work. This is the same sample used by the
repository's automated tests, sourced from
[whisper.cpp v1.9.5](https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/samples/jfk.wav).

## Try a sample

```bash
curl -N -F 'file=@test_files/speech-us-female.wav' \
  'http://127.0.0.1:8000/transcribe?format=sse&diarization=true&include_audio=true'
```

In the Polyvox Postman environment, set `audio_file` to any path above, such as
`test_files/speech-us-female.wav`,
and set Postman's working directory to the project root. Alternatively, select
this file through **Body > form-data > file**.
