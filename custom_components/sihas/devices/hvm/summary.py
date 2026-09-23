"""HVM legacy room-summary compatibility semantics."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

HVM_COUNT = 21
HVM_STATE_START = 52
HVM_TEMP_UNIT = 59
_POWER = 1
_VALVE = 8
_CURRENT = 0x03F0
_TARGET = 0xFC00


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
    return 0.5 if registers[HVM_TEMP_UNIT] != 0 else 1


def room_count(registers: Sequence[int]) -> int:
    return registers[HVM_COUNT]


def room_register(index: int) -> int:
    return HVM_STATE_START + index


def decode(registers: Sequence[int]) -> tuple[RoomState, ...]:
    return tuple(decode_room(registers[room_register(index)], magnification(registers))
                 for index in range(room_count(registers)))


def room_state(state: Sequence[RoomState], room: int) -> RoomState:
    return state[room]
