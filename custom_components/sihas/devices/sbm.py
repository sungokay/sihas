"""SBM family state and command semantics."""
from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING

from .definition import DeviceDefinition, Feature, register_writes

if TYPE_CHECKING:
    from .state import DeviceSnapshot


def switch_channel_count(config: int) -> int:
    return config


def decode_switch_channel(registers: Sequence[int], channel: int) -> bool:
    return registers[channel] == 1


class SbmState(tuple):
    """Per-channel on/off in channel order."""


def decode_switches(registers: Sequence[int], config: int) -> SbmState:
    return SbmState(decode_switch_channel(registers, index) for index in range(switch_channel_count(config)))


def switch_command(channel: int, powered: bool) -> tuple[int, int]:
    return channel, 1 if powered else 0


def channel_intents(snapshot: DeviceSnapshot, powered: bool, *, channel: int) -> tuple[tuple[int, int]]:
    return (switch_command(channel, powered),)


def definition(config: int) -> DeviceDefinition:
    """One `channel_<n>` power command per configured channel: one register write, then one readback refresh."""
    return DeviceDefinition(decode=partial(decode_switches, config=config), features={
        f"channel_{channel}": Feature(read_supported=True, command=register_writes(partial(channel_intents, channel=channel), refresh=True))
        for channel in range(switch_channel_count(config))
    })
