"""RBM family state and command semantics."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RbmState:
    closed: bool
    closing: bool
    opening: bool
    position: int


def decode_rbm(registers: Sequence[int]) -> RbmState:
    return RbmState(registers[2] == 0, registers[2] == 3, registers[2] == 4, registers[3])


def rbm_motion_command(motion: str) -> tuple[int, int]:
    return 0, {"close": 0, "open": 1, "stop": 2}[motion]


def rbm_position_command(position: int) -> tuple[int, int]:
    return 1, position
