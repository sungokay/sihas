"""SDM family state and command semantics."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from .definition import DeviceDefinition, Feature, register_writes

if TYPE_CHECKING:
    from .state import DeviceSnapshot

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


class SdmState(tuple):
    """Per-channel dimmer states in channel order."""


def decode_dimmers(registers: Sequence[int], config: int) -> SdmState:
    return SdmState(decode_dimmer(registers, index) for index in range(dimmer_channel_count(config)))


def dimmer_command(channel: int, level: int) -> tuple[int, int]:
    return dimmer_register(channel), level


def dimmer_on_command(channel: int) -> tuple[int, int]:
    return dimmer_command(channel, 101)


def dimmer_off_command(channel: int) -> tuple[int, int]:
    return dimmer_command(channel, 0)


def dimmer_on_intent(channel: int, level: int | None) -> tuple[int, int]:
    """Select the full-on intent when no explicit level is requested."""
    return dimmer_on_command(channel) if level is None else dimmer_command(channel, level)


def channel_intents(snapshot: DeviceSnapshot, value: bool | int, *, channel: int) -> tuple[tuple[int, int]]:
    """False turns the channel off, True selects the full-on intent, and a number is the explicit level."""
    if value is False:
        return (dimmer_off_command(channel),)
    return (dimmer_on_intent(channel, None if value is True else value),)


def definition(config: int) -> DeviceDefinition:
    """One `channel_<n>` command per configured channel: one register write, then one readback refresh."""
    return DeviceDefinition(decode=partial(decode_dimmers, config=config), features={
        f"channel_{channel}": Feature(read_supported=True, command=register_writes(partial(channel_intents, channel=channel), refresh=True))
        for channel in range(dimmer_channel_count(config))
    })
