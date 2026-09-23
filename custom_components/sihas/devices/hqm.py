"""HQM standalone and multi-room semantics."""

from collections.abc import Sequence
from dataclasses import dataclass

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


def room_target(value: int, temperature: float, magnification: float) -> int:
    return (value & ~_TARGET) | (int(temperature / magnification) << 10)


def hqm_is_standalone(registers: Sequence[int], config: int) -> bool:
    return config == 0 or registers[HQM_SLAVE] != 0


def hqm_room_count(registers: Sequence[int]) -> int:
    return registers[HQM_COUNT]


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
    return HQM_TARGET, int(temperature * 10)
