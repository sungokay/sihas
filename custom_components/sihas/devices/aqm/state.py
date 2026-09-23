"""AQM measurement decoding and read-state composition."""

from collections.abc import Sequence
from dataclasses import dataclass
from .metadata import AqmMetadata, decode_metadata, is_word
from .link import SelectedLink, decode_selected_link
from .settings import AqmSettings, decode_settings
from ..numeric import reg_to_int16


def aqm_humidity(r: Sequence[int]) -> float:
    return round(r[1] / 10, 1)


def aqm_temperature(r: Sequence[int]) -> float:
    return round(reg_to_int16(r[0]) / 10, 1)


def aqm_illuminance(r: Sequence[int]) -> int:
    return r[6]


def aqm_co2(r: Sequence[int]) -> int:
    return r[2]


def aqm_pm25(r: Sequence[int]) -> int:
    return r[3]


def aqm_pm10(r: Sequence[int]) -> int:
    return r[4]


def aqm_tvoc(r: Sequence[int]) -> int:
    return r[5]


@dataclass(frozen=True)
class AqmState:
    humidity: float
    temperature: float
    illuminance: int
    co2: int
    pm25: int
    pm10: int
    tvoc: int
    metadata: AqmMetadata | None = None
    settings: AqmSettings | None = None
    selected_link: SelectedLink | None = None


def decode_aqm(registers: Sequence[int], *, config: int | None = None, firmware: str | None = None) -> AqmState:
    if len(registers) < 7 or not all(is_word(word) for word in registers[:7]):
        raise ValueError("AQM measurements require seven unsigned register words")
    metadata = decode_metadata(registers, config=config, firmware=firmware)
    return AqmState(
        aqm_humidity(registers),
        aqm_temperature(registers),
        aqm_illuminance(registers),
        aqm_co2(registers),
        aqm_pm25(registers),
        aqm_pm10(registers),
        aqm_tvoc(registers),
        metadata,
        decode_settings(registers, display=metadata.display),
        decode_selected_link(registers),
    )
