"""Model-independent streaming contracts. Times are absolute seconds in a session."""

from array import array
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: str


class Recognizer(Protocol):
    """Return only committed words, once each; retain encoder state between pushes."""

    language: str
    device: str

    def push(self, samples: array) -> list[Word]: ...
    def finish(self) -> list[Word]: ...
    def close(self) -> None: ...


class Diarizer(Protocol):
    """Keep speaker IDs stable across pushes. Never relabel before stable_until."""

    device: str
    stable_until: float

    def push(self, samples: array) -> None: ...
    def finish(self) -> None: ...
    def turns(self) -> list[Turn]: ...
    def close(self) -> None: ...
