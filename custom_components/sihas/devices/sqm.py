"""SQM family state and command semantics."""

from collections.abc import Sequence


def switch_channel_count(config: int) -> int:
    return config


def decode_switch_channel(registers: Sequence[int], channel: int) -> bool:
    return registers[channel] == 1


def decode_switches(registers: Sequence[int], config: int) -> tuple[bool, ...]:
    return tuple(decode_switch_channel(registers, index) for index in range(switch_channel_count(config)))


def switch_command(channel: int, powered: bool) -> tuple[int, int]:
    return channel, 1 if powered else 0
