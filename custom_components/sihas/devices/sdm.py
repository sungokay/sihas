"""SDM family state and command semantics."""

from collections.abc import Sequence
from dataclasses import dataclass

DIMMER_LEVEL_RANGE = (1, 100)


@dataclass(frozen=True)
class DimmerState:
    # Preserve the existing raw on/off value, including unclassified values.
    power: int
    level: int


def dimmer_channel_count(config: int) -> int:
    return config & 0x07


def dimmer_register(channel: int) -> int:
    return channel * 2


def decode_dimmer(registers: Sequence[int], channel: int) -> DimmerState:
    value = registers[dimmer_register(channel)]
    return DimmerState(value, value)


def decode_dimmers(registers: Sequence[int], config: int) -> tuple[DimmerState, ...]:
    return tuple(decode_dimmer(registers, index) for index in range(dimmer_channel_count(config)))


def dimmer_command(channel: int, level: int) -> tuple[int, int]:
    return dimmer_register(channel), level


def dimmer_on_command(channel: int) -> tuple[int, int]:
    return dimmer_command(channel, 101)


def dimmer_off_command(channel: int) -> tuple[int, int]:
    return dimmer_command(channel, 0)


def dimmer_on_intent(channel: int, level: int | None) -> tuple[int, int]:
    """Select the full-on intent when no explicit level is requested."""
    return dimmer_on_command(channel) if level is None else dimmer_command(channel, level)
