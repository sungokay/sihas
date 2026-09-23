"""Existing TCM temperature and run-mode interpretation."""
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from .definition import CommandExecution

POWER = 0
TARGET = 1
CURRENT = 3
RUN_MODE = 7


class RunMode(IntEnum):
    HEATING = 0
    COOLING = 1


@dataclass(frozen=True)
class TcmState:
    powered: bool
    mode: RunMode
    current_temperature: float
    target_temperature: float


def decode(registers: Sequence[int]) -> TcmState:
    return TcmState(registers[POWER] != 0, RunMode(registers[RUN_MODE]), registers[CURRENT] / 10, registers[TARGET] / 10)


def power_command(powered: bool) -> tuple[int, int]:
    return POWER, 1 if powered else 0


def mode_command(heating: bool) -> tuple[int, int]:
    return RUN_MODE, RunMode.HEATING if heating else RunMode.COOLING


def temperature_command(temperature: float) -> tuple[int, int]:
    return TARGET, int(temperature * 10)


async def async_mode_transition(mode: str, execution: CommandExecution) -> None:
    """Preserve the verified TCM power-then-mode sequencing."""
    if mode == "off":
        await execution.write(power_command(False))
        return
    await execution.write(power_command(True))
    await execution.write(mode_command(mode == "heat"))
