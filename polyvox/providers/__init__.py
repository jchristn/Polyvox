"""Replace either model through configuration or an installed provider factory."""

import importlib

from ..errors import ConfigurationError
from .base import Diarizer, Recognizer, Turn, Word

__all__ = ["Diarizer", "Recognizer", "Turn", "Word", "create_provider"]


def create_provider(kind, settings):
    name = settings.asr_provider if kind == "asr" else settings.diarization_provider
    if name == "nemo":
        from .nemo import NemoDiarizer, NemoRecognizer

        factory = NemoRecognizer if kind == "asr" else NemoDiarizer
    else:
        try:
            module, attribute = name.split(":", 1)
            factory = getattr(importlib.import_module(module), attribute)
        except (ValueError, ImportError, AttributeError) as exc:
            raise ConfigurationError(f"Cannot load {kind} provider {name}") from exc
    return factory(settings)
