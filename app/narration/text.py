"""Small text helpers shared by the narration pipeline."""
from __future__ import annotations
import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"\s+")


def split_sentences(text: str) -> list[str]:
    """Split narration prose into trimmed sentences."""
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split((text or "").strip()) if sentence.strip()]


def clean(text: str) -> str:
    """Collapse whitespace/newlines so the text is TTS-safe."""
    return _WHITESPACE.sub(" ", (text or "").strip())


def word_count(text: str) -> int:
    return len((text or "").split())
