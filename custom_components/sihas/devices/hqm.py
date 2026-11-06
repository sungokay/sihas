"""HQM standalone and multi-room semantics."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from functools import partial
from typing import TYPE_CHECKING

from .definition import DeviceDefinition, Feature, register_writes

if TYPE_CHECKING:
    from .state import DeviceSnapshot

HQM_MAGNIFICATION = 0.5
HQM_COUNT = 16
HQM_STATE_START = 23
HQM_ONOFF = 0
HQM_TARGET = 1
HQM_CURRENT = 4
HQM_VALVE = 5
HQM_HUMIDITY = 7
HQM_SLAVE = 9
_POWER = 1
_VALVE = 8
_CURRENT = 0x03F0
_TARGET = 0xFC00
# The six-bit target field holds codes 0..63 in units of the temperature step.
TARGET_MAX_CODE = _TARGET >> 10
# A multi-room HQM has at most seven rooms, R23..R29; the live room count selects which rooms exist.
MAX_ROOMS = 7
ROOM_SLOTS = MAX_ROOMS


@dataclass(frozen=True)
class RoomState:
    current_temperature: float
    target_temperature: float
    powered: bool
    valve_open: bool
    temperature_step: float


@dataclass(frozen=True)
class HqmStandaloneState:
    powered: bool
    current_temperature: float
    target_temperature: float
    action: str | None
    raw_power: int
    raw_valve: int


@dataclass(frozen=True)
class HqmState:
    rooms: tuple[RoomState, ...]
    standalone: HqmStandaloneState | None
    humidity: int


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
        raise ValueError(f"HQM target {temperature} is outside 0..{target_maximum(magnification)}")
    return (value & ~_TARGET) | (code << 10)


def hqm_is_standalone(registers: Sequence[int], config: int) -> bool:
    return config == 0 or registers[HQM_SLAVE] != 0


def hqm_room_count(registers: Sequence[int]) -> int:
    count = registers[HQM_COUNT]
    if count > MAX_ROOMS:
        raise ValueError(f"HQM reports {count} rooms; at most {MAX_ROOMS} exist")
    return count


def hqm_room_register(index: int) -> int:
    return HQM_STATE_START + index


room_register = hqm_room_register


def room_state(state: HqmState, room: int) -> RoomState:
    return state.rooms[room]


def hqm_humidity(registers: Sequence[int]) -> int:
    return registers[HQM_HUMIDITY]


def decode_hqm_standalone(registers: Sequence[int]) -> HqmStandaloneState:
    power, valve = registers[HQM_ONOFF], registers[HQM_VALVE]
    action = "off" if power == 0 else "idle" if valve == 0 else "heating" if valve == 1 else None
    return HqmStandaloneState(power != 0, registers[HQM_CURRENT] / 10, registers[HQM_TARGET] / 10, action, power, valve)


def decode_hqm(registers: Sequence[int], config: int) -> HqmState:
    standalone = hqm_is_standalone(registers, config)
    return HqmState(
        () if standalone else tuple(decode_room(registers[hqm_room_register(index)], HQM_MAGNIFICATION) for index in range(hqm_room_count(registers))),
        decode_hqm_standalone(registers) if standalone else None, hqm_humidity(registers),
    )


def hqm_power_command(powered: bool) -> tuple[int, int]:
    return HQM_ONOFF, 1 if powered else 0


def hqm_temperature_command(temperature: float) -> tuple[int, int]:
    return HQM_TARGET, _nearest_steps(temperature, 0.1)


def room_power_intents(snapshot: DeviceSnapshot, powered: bool, *, room: int) -> tuple[tuple[int, int]]:
    """Bit0 edit of the room's transaction-start summary word; every other bit is preserved."""
    index = room_register(room)
    return ((index, room_power(snapshot.registers[index], powered)),)


def room_target_intents(snapshot: DeviceSnapshot, temperature: float, *, room: int) -> tuple[tuple[int, int]]:
    """Target field edit of the room's transaction-start summary word at the room's published step."""
    index = room_register(room)
    return ((index, room_target(snapshot.registers[index], temperature, room_state(snapshot.state, room).temperature_step)),)


def definition(config: int) -> DeviceDefinition:
    """Standalone power/target and multi-room commands; each is one register write followed by one readback refresh."""
    return DeviceDefinition(decode=partial(decode_hqm, config=config), features={
        "power": Feature(read_supported=True, command=register_writes(lambda snapshot, value: (hqm_power_command(value),), refresh=True)),
        "temperature": Feature(read_supported=True,
                               command=register_writes(lambda snapshot, value: (hqm_temperature_command(value),), refresh=True)),
        **{f"room_{room}_power": Feature(command=register_writes(partial(room_power_intents, room=room), refresh=True))
           for room in range(ROOM_SLOTS)},
        **{f"room_{room}_target": Feature(command=register_writes(partial(room_target_intents, room=room), refresh=True))
           for room in range(ROOM_SLOTS)},
    })
