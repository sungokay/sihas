"""HCM legacy room-summary compatibility semantics."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from functools import partial
from typing import TYPE_CHECKING

from .definition import DeviceDefinition, Feature, register_writes

if TYPE_CHECKING:
    from .state import DeviceSnapshot

HCM_COUNT = 18
HCM_STATE_START = 52
HCM_TEMP_UNIT = 59
_POWER = 1
_VALVE = 8
_CURRENT = 0x03F0
_TARGET = 0xFC00
# Room words addressable inside the 64-register poll; the live room count selects which rooms exist.
ROOM_SLOTS = 64 - HCM_STATE_START


@dataclass(frozen=True)
class RoomState:
    current_temperature: float
    target_temperature: float
    powered: bool
    valve_open: bool
    temperature_step: float


def decode_room(value: int, magnification: float) -> RoomState:
    return RoomState(
        ((value & _CURRENT) >> 4) * magnification,
        ((value & _TARGET) >> 10) * magnification,
        value & _POWER == 1, bool(value & _VALVE), magnification,
    )


def room_power(value: int, powered: bool) -> int:
    return (value & ~_POWER) | (1 if powered else 0)


def _nearest_steps(temperature: float, step: float) -> int:
    """Whole `step` units nearest to `temperature`; an exact midpoint selects the higher temperature.

    Decimal arithmetic on the shortest float text keeps midpoint decisions independent of binary representation error.
    """
    units = Decimal(str(temperature)) / Decimal(str(step))
    return int((units + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def room_target(value: int, temperature: float, magnification: float) -> int:
    return (value & ~_TARGET) | (_nearest_steps(temperature, magnification) << 10)


def magnification(registers: Sequence[int]) -> float:
    return 0.5 if registers[HCM_TEMP_UNIT] != 0 else 1


def room_count(registers: Sequence[int]) -> int:
    return registers[HCM_COUNT]


def room_register(index: int) -> int:
    return HCM_STATE_START + index


class HcmState(tuple):
    """HCM rooms in room order; indexing and length are the room summary."""


def decode(registers: Sequence[int]) -> HcmState:
    return HcmState(decode_room(registers[room_register(index)], magnification(registers))
                    for index in range(room_count(registers)))


def room_state(state: Sequence[RoomState], room: int) -> RoomState:
    return state[room]


def room_power_intents(snapshot: DeviceSnapshot, powered: bool, *, room: int) -> tuple[tuple[int, int]]:
    """Bit0 edit of the room's transaction-start summary word; every other bit is preserved."""
    index = room_register(room)
    return ((index, room_power(snapshot.registers[index], powered)),)


def room_target_intents(snapshot: DeviceSnapshot, temperature: float, *, room: int) -> tuple[tuple[int, int]]:
    """Target field edit of the room's transaction-start summary word at the room's published step."""
    index = room_register(room)
    return ((index, room_target(snapshot.registers[index], temperature, room_state(snapshot.state, room).temperature_step)),)


# Each room command is one register write followed by one readback refresh.
DEFINITION = DeviceDefinition(decode=decode, features={
    **{f"room_{room}_power": Feature(command=register_writes(partial(room_power_intents, room=room), refresh=True)) for room in range(ROOM_SLOTS)},
    **{f"room_{room}_target": Feature(command=register_writes(partial(room_target_intents, room=room), refresh=True))
       for room in range(ROOM_SLOTS)},
})
