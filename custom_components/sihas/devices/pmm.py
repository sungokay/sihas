"""PMM power-meter measurement decoding."""

from collections.abc import Sequence
from dataclasses import dataclass
from .numeric import register_put_u32

PMM_MAG_TABLE = {0: 10, 1: 100, 2: 1000}


def as_killo_watt(watt: int) -> float:
    return round(watt / 1000, 2)


def this_month_value_handler(registers: Sequence[int]) -> float:
    try:
        mag = PMM_MAG_TABLE[registers[31]]
        return as_killo_watt(registers[10] * mag + registers[16])
    except IndexError as e:
        raise ValueError(f"PMM-300 월간 사용량 배율을 해석하지 못했습니다.") from e


def last_month_value_handler(registers: Sequence[int]) -> float:
    try:
        mag = PMM_MAG_TABLE[registers[31]]
        return as_killo_watt(registers[11] * mag)
    except IndexError as e:
        raise ValueError(f"PMM-300 월간 사용량 배율을 해석하지 못했습니다.") from e


def pmm_power(r: Sequence[int]) -> int:
    return (r[37] << 16) | r[2]


def pmm_this_day_energy(r: Sequence[int]) -> float:
    return as_killo_watt(r[8] * 10 + r[16])


def pmm_total_energy(r: Sequence[int]) -> float:
    return as_killo_watt(register_put_u32(r[40], r[41]))


def pmm_voltage(r: Sequence[int]) -> float:
    return r[0] / 10


def pmm_current(r: Sequence[int]) -> float:
    return r[1] / 100


def pmm_power_factor(r: Sequence[int]) -> float:
    return r[3] / 10


def pmm_frequency(r: Sequence[int]) -> float:
    return r[4] / 10


@dataclass(frozen=True)
class PmmState:
    power: int
    this_month_energy: float
    this_day_energy: float
    total_energy: float
    last_month_energy: float
    voltage: float
    current: float
    power_factor: float
    frequency: float


def decode_pmm(registers: Sequence[int]) -> PmmState:
    return PmmState(
        pmm_power(registers),
        this_month_value_handler(registers),
        pmm_this_day_energy(registers),
        pmm_total_energy(registers),
        last_month_value_handler(registers),
        pmm_voltage(registers),
        pmm_current(registers),
        pmm_power_factor(registers),
        pmm_frequency(registers),
    )
