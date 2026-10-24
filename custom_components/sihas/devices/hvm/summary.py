"""HVM legacy room-summary compatibility semantics."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..state import DeviceSnapshot

HVM_COUNT = 21
HVM_STATE_START = 52
HVM_TEMP_UNIT = 59
_POWER = 1
_VALVE = 8
_CURRENT = 0x03F0
_TARGET = 0xFC00
# The six-bit target field holds codes 0..63 in units of the temperature step.
TARGET_MAX_CODE = _TARGET >> 10
# An HVM controller has at most seven rooms, R52..R58.
MAX_ROOMS = 7


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


def target_maximum(step: float) -> float:
    """Highest target temperature the six-bit field can encode at `step`."""
    return TARGET_MAX_CODE * step


def room_target(value: int, temperature: float, magnification: float) -> int:
    code = _nearest_steps(temperature, magnification)
    if not 0 <= code <= TARGET_MAX_CODE:
        raise ValueError(f"HVM target {temperature} is outside 0..{target_maximum(magnification)}")
    return (value & ~_TARGET) | (code << 10)


def magnification(registers: Sequence[int]) -> float:
    return 0.5 if registers[HVM_TEMP_UNIT] != 0 else 1


def room_count(registers: Sequence[int]) -> int:
    count = registers[HVM_COUNT]
    if count > MAX_ROOMS:
        raise ValueError(f"HVM reports {count} rooms; at most {MAX_ROOMS} exist")
    return count


def room_register(index: int) -> int:
    return HVM_STATE_START + index


def decode(registers: Sequence[int]) -> tuple[RoomState, ...]:
    return tuple(decode_room(registers[room_register(index)], magnification(registers))
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
