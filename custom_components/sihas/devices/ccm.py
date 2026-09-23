"""CCM family state and command semantics."""

from collections.abc import Sequence
from dataclasses import dataclass

from .definition import CommandExecution


@dataclass(frozen=True)
class CcmState:
    powered: bool
    voltage: float
    current: float
    power: float
    power_factor: float


def decode_ccm(registers: Sequence[int]) -> CcmState:
    return CcmState(registers[0] == 1, round(registers[1] * 0.01, 3), round(registers[2] * 0.001, 3),
                    round(registers[3] * 0.1, 3), round(registers[4] * 0.1, 3))


def ccm_power_command(powered: bool) -> tuple[int, int]:
    return 0, 1 if powered else 0


async def async_power(powered: bool, execution: CommandExecution) -> None:
    """CCM alone uses a single physical attempt and propagates write failures."""
    if execution.write_once is None:
        raise ValueError("Single-attempt execution is unavailable")
    await execution.write_once(ccm_power_command(powered))
