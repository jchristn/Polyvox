"""ctypes declarations for the pinned NeMo-Speech.cpp v0.3.0 public C ABI.

Structs are size-prefixed; definitions follow include/nemo_speech/{asr,diar}.h.
No C++ implementation types cross this boundary.
"""

import ctypes as c

P = c.c_void_p
Z = c.c_size_t
INT = c.c_int32
F = c.c_float
D = c.c_double
S = c.c_char_p
B = c.c_bool


class Sized(c.Structure):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size = c.sizeof(self)


class Backend(Sized):
    _fields_ = [("size", Z), ("gpu", INT)]


class Model(Sized):
    _fields_ = [("size", Z), ("path", S), ("name", S)]


class Endpointing(Sized):
    _fields_ = [("size", Z), ("enable", B), ("vad_based", B), ("stop_history_eou_ms", INT)]


class RecognizerConfig(Sized):
    _fields_ = [("size", Z)] + [
        (name, P)
        for name in (
            "backend",
            "model",
            "streaming",
            "decoder",
            "vad",
            "endpointing",
            "postproc",
            "diar",
            "batching",
            "salm",
        )
    ]


class Options(Sized):
    _fields_ = [
        ("size", Z),
        ("request_id", S),
        ("language_code", S),
        ("interim_results", B),
        ("enable_word_time_offsets", B),
        ("enable_automatic_punctuation", B),
        ("verbatim_transcripts", B),
        ("profanity_filter", B),
        ("stop_history_eou_ms", INT),
        ("speech_contexts", P),
        ("speech_context_count", Z),
        ("max_alternatives", INT),
        ("enable_speaker_diarization", B),
        ("max_speaker_count", INT),
    ]


class DiarConfig(Sized):
    _fields_ = [("size", Z), ("model_path", S), ("gpu", INT), ("preset", S)] + [
        (name, INT)
        for name in (
            "chunk_frames",
            "right_context_frames",
            "left_context_frames",
            "fifo_frames",
            "spkcache_frames",
            "update_period_frames",
        )
    ]


class Segment(c.Structure):
    _fields_ = [("start_time", D), ("end_time", D), ("speaker", INT)]


def bind(lib):
    signatures = {
        "asr_last_error": (S, []),
        "asr_create": (INT, [c.POINTER(RecognizerConfig), c.POINTER(P)]),
        "asr_destroy": (None, [P]),
        "asr_recognition_options_default": (Options, []),
        "asr_streaming_recognize": (INT, [P, c.POINTER(Options), c.POINTER(P)]),
        "asr_stream_push_f32": (INT, [P, c.POINTER(F), Z, INT]),
        "asr_stream_next": (INT, [P, c.POINTER(P)]),
        "asr_stream_finish": (INT, [P]),
        "asr_stream_force_endpoint": (INT, [P]),
        "asr_stream_close": (None, [P]),
        "asr_result_is_final": (B, [P]),
        "asr_result_word_count": (Z, [P, Z]),
        "asr_result_word_text": (S, [P, Z, Z]),
        "asr_result_word_start_time": (INT, [P, Z, Z]),
        "asr_result_word_end_time": (INT, [P, Z, Z]),
        "asr_result_language_count": (Z, [P, Z]),
        "asr_result_language_code": (S, [P, Z, Z]),
        "asr_result_destroy": (None, [P]),
        "diar_create": (INT, [c.POINTER(DiarConfig), c.POINTER(P)]),
        "diar_destroy": (None, [P]),
        "diar_stream_open": (INT, [P, c.POINTER(P)]),
        "diar_stream_push_f32": (INT, [P, c.POINTER(F), Z, INT]),
        "diar_stream_finish": (INT, [P]),
        "diar_stream_close": (None, [P]),
        "diar_seconds_per_frame": (D, [P]),
        "diar_frame_count": (c.c_int64, [P]),
        "diar_segments": (INT, [P, P, c.POINTER(Segment), Z, c.POINTER(Z)]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(lib, "nemo_speech_" + name)
        function.restype, function.argtypes = result, arguments
        setattr(lib, name, function)
    return lib
