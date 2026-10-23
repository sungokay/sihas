"""Neutral Diagnostics privacy contract that family interpretations declare; no HA or I/O."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SensitiveField:
    """Family-evidenced R[start:end] and exact decoded alias paths (end exclusive)."""

    start: int
    end: int
    aliases: tuple[tuple[str | int, ...], ...]
    reason: str
    provenance: str
