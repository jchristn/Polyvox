"""Stateful ASR and diarization adapters for NeMo-Speech.cpp's public C ABI."""

import ctypes as c
import functools
import math
import os
import sys
from array import array
from pathlib import Path

from ..config import runtime_library
from ..errors import BackendFailure, ConfigurationError
from . import _abi as abi
from .base import Turn, Word

SAMPLE_RATE = 16000


@functools.lru_cache(maxsize=4)
def runtime(directory):
    path = runtime_library(directory)
    # Keep Windows DLL search handles alive as long as the runtime is loaded.
    handles = []
    if sys.platform == "win32":
        handles.append(os.add_dll_directory(str(path.parent)))
    try:
        lib = abi.bind(c.CDLL(str(path)))
        lib._directory_handles = handles
        # Windows GetProcAddress does not resolve exports in dependent DLLs.
        # Load ggml itself explicitly on every platform for one portable path.
        ggml_name = {
            "win32": "ggml.dll",
            "darwin": "libggml.dylib",
        }.get(sys.platform, "libggml.so")
        lib._ggml = c.CDLL(str(path.parent / ggml_name))
        load = lib._ggml.ggml_backend_load_all_from_path
        load.argtypes, load.restype = [c.c_char_p], None
        load(os.fsencode(path.parent))
        return lib
    except (OSError, AttributeError) as exc:
        for handle in handles:
            handle.close()
        raise ConfigurationError(f"Incompatible NeMo-Speech runtime: {path}") from exc


def selected_gpu(lib, device, index):
    if device == "cpu":
        return -1
    lib = lib._ggml
    for name, restype, argtypes in (
        ("count", c.c_size_t, []),
        ("get", c.c_void_p, [c.c_size_t]),
        ("type", c.c_int, [c.c_void_p]),
        ("name", c.c_char_p, [c.c_void_p]),
        ("description", c.c_char_p, [c.c_void_p]),
    ):
        function = getattr(lib, "ggml_backend_dev_" + name)
        function.restype, function.argtypes = restype, argtypes
    devices = [lib.ggml_backend_dev_get(i) for i in range(lib.ggml_backend_dev_count())]
    devices = [d for d in devices if lib.ggml_backend_dev_type(d) in (1, 2)]
    if index >= len(devices):
        raise ConfigurationError(f"No {device} GPU at index {index}")
    selected = devices[index]
    name = lib.ggml_backend_dev_name(selected).decode().lower()
    description = lib.ggml_backend_dev_description(selected).decode().lower()
    expected = {
        "metal": ("mtl", "metal"),
        "cuda": ("cuda",),
        "rocm": ("rocm", "hip"),
        "vulkan": ("vulkan",),
        "qualcomm": ("vulkan",),
    }[device]
    if not any(value in name for value in expected):
        raise ConfigurationError(f"Requested {device}, selected GPU is {name}")
    if device == "qualcomm" and not any(v in description for v in ("adreno", "qualcomm")):
        raise ConfigurationError("Selected Vulkan device is not Qualcomm Adreno")
    return index


def check(lib, status):
    if status:
        detail = (lib.asr_last_error() or b"Native inference failed").decode(errors="replace")
        error = ConfigurationError if status == 1 else BackendFailure
        raise error(detail)


def pcm_pointer(samples):
    if samples.typecode != "f" or samples.itemsize != 4:
        raise ValueError("Providers require float32 PCM")
    return (c.c_float * len(samples)).from_buffer(samples)


class NemoRecognizer:
    def __init__(self, settings):
        self.lib = runtime(settings.runtime_dir)
        self.device = settings.device
        self.language = settings.language if settings.language != "auto" else "unknown"
        self.model, self.stream = abi.P(), abi.P()
        self.frames = 0
        self.endpoint_frames = int(settings.segment_seconds * SAMPLE_RATE)
        self.next_endpoint = self.endpoint_frames
        backend = abi.Backend(gpu=selected_gpu(self.lib, self.device, settings.gpu_device))
        model = abi.Model(path=os.fsencode(Path(settings.model_path).resolve()))
        endpoint = abi.Endpointing(enable=True, vad_based=False, stop_history_eou_ms=600)
        config = abi.RecognizerConfig(
            backend=c.addressof(backend),
            model=c.addressof(model),
            endpointing=c.addressof(endpoint),
        )
        try:
            check(self.lib, self.lib.asr_create(c.byref(config), c.byref(self.model)))
            options = self.lib.asr_recognition_options_default()
            options.interim_results = False
            options.enable_word_time_offsets = True
            options.enable_automatic_punctuation = True
            options.language_code = (
                settings.language.encode() if settings.language != "auto" else None
            )
            check(
                self.lib,
                self.lib.asr_streaming_recognize(
                    self.model, c.byref(options), c.byref(self.stream)
                ),
            )
        except BaseException:
            self.close()
            raise

    def _drain(self):
        words = []
        while True:
            result = abi.P()
            check(self.lib, self.lib.asr_stream_next(self.stream, c.byref(result)))
            if not result:
                break
            try:
                if not self.lib.asr_result_is_final(result):
                    continue
                for i in range(self.lib.asr_result_word_count(result, 0)):
                    words.append(
                        Word(
                            self.lib.asr_result_word_start_time(result, 0, i) / 1000,
                            self.lib.asr_result_word_end_time(result, 0, i) / 1000,
                            self.lib.asr_result_word_text(result, 0, i).decode("utf-8"),
                        )
                    )
                if self.lib.asr_result_language_count(result, 0):
                    self.language = self.lib.asr_result_language_code(result, 0, 0).decode()
            finally:
                self.lib.asr_result_destroy(result)
        return words

    def push(self, samples: array) -> list[Word]:
        check(
            self.lib,
            self.lib.asr_stream_push_f32(
                self.stream, pcm_pointer(samples), len(samples), SAMPLE_RATE
            ),
        )
        self.frames += len(samples)
        if self.frames >= self.next_endpoint:
            # Bound final-caption latency even during speech with no pauses.
            check(self.lib, self.lib.asr_stream_force_endpoint(self.stream))
            self.next_endpoint = self.frames + self.endpoint_frames
        return self._drain()

    def finish(self):
        check(self.lib, self.lib.asr_stream_finish(self.stream))
        return self._drain()

    def close(self):
        if self.stream:
            self.lib.asr_stream_close(self.stream)
            self.stream = abi.P()
        if self.model:
            self.lib.asr_destroy(self.model)
            self.model = abi.P()


class NemoDiarizer:
    def __init__(self, settings):
        self.lib = runtime(settings.runtime_dir)
        self.device = settings.diarization_device
        self.model, self.stream = abi.P(), abi.P()
        self.stable_until = 0.0
        # Pinned SDK segmentation can pad/merge/drop recent turns. Cover its
        # default temporal reach (0.511 + 0.296 + 0.229 + 0.079 seconds).
        # A caller may add latency, but cannot bypass final-label safety.
        self.holdback = max(1.2, settings.diarization_holdback)
        config = abi.DiarConfig(
            model_path=os.fsencode(Path(settings.diarization_model).resolve()),
            gpu=selected_gpu(self.lib, self.device, settings.gpu_device),
            left_context_frames=-1,
        )
        try:
            check(self.lib, self.lib.diar_create(c.byref(config), c.byref(self.model)))
            check(self.lib, self.lib.diar_stream_open(self.model, c.byref(self.stream)))
            self.frame_seconds = self.lib.diar_seconds_per_frame(self.model)
            # V2 has a retrospective channel-birth gate whose stable frontier
            # is not exposed by this C ABI. V3's 10 ms frames are committed by
            # ordinary pushes (we never request provisional flushes).
            if not math.isclose(self.frame_seconds, 0.01, abs_tol=1e-6):
                raise ConfigurationError(
                    "The nemo diarizer requires a V3 model with 10 ms output; "
                    "use a separate provider for other stability semantics"
                )
        except BaseException:
            self.close()
            raise

    def push(self, samples: array):
        check(
            self.lib,
            self.lib.diar_stream_push_f32(
                self.stream, pcm_pointer(samples), len(samples), SAMPLE_RATE
            ),
        )
        self.stable_until = max(
            0, self.lib.diar_frame_count(self.stream) * self.frame_seconds - self.holdback
        )

    def finish(self):
        check(self.lib, self.lib.diar_stream_finish(self.stream))
        self.stable_until = math.inf

    def turns(self):
        count = abi.Z()
        check(self.lib, self.lib.diar_segments(self.stream, None, None, 0, c.byref(count)))
        segments = (abi.Segment * count.value)()
        check(
            self.lib,
            self.lib.diar_segments(self.stream, None, segments, count.value, c.byref(count)),
        )
        return [Turn(s.start_time, s.end_time, f"SPEAKER_{s.speaker - 1:02d}") for s in segments]

    def close(self):
        if self.stream:
            self.lib.diar_stream_close(self.stream)
            self.stream = abi.P()
        if self.model:
            self.lib.diar_destroy(self.model)
            self.model = abi.P()
