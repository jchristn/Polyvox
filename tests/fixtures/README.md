# Speech fixture

`jfk.wav` is the 11-second John F. Kennedy speech sample distributed by
whisper.cpp v1.9.5:
https://github.com/ggml-org/whisper.cpp/blob/v1.9.5/samples/jfk.wav

The speech is a US federal government work. The fixture is used to check that
real inference produces recognizable words, rather than merely a successful
process exit. Tests look for “ask” and “country”; they do not demand identical
punctuation or tokenization across accelerators.
