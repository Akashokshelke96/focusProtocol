"""Deterministic seed helpers shared by character and scene generation."""
from __future__ import annotations

import hashlib


def stable_seed(base: int, *parts: object) -> int:
    """Return a stable 31-bit seed from a base seed plus semantic parts.

    ``NARRATION_SEED=0`` no longer means "random": it means "derive a stable
    seed from the prompt/identity", so a resumed job reproduces the same cast
    and the same scene images.
    """
    payload = "::".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    offset = int.from_bytes(digest[:4], "big")
    return (int(base) + offset) % (2 ** 31 - 1)
