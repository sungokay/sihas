"""AQM app-static settings codecs. Encoding never qualifies a device writer.

Observed raw values are retained even outside app guidance. No setting owns a
register snapshot, metadata, I/O, or HA exposure. Display interpretation comes
from the existing AQM metadata owner.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
from typing import Literal

from .metadata import Quality
from .metadata import is_word


class BacklightMode(IntEnum):
    ALWAYS_OFF = 0
    ALWAYS_ON = 1
    AUTO_OFF = 2
    ILLUMINANCE = 3


class FndPrimary(IntEnum):
    PM25 = 0
    PM10 = 1
    CYCLE = 2


class FndSecondary(IntEnum):
    TVOC = 0
    TIME = 1
    CYCLE = 2


class LcdPrimary(IntEnum):
    PM25 = 0
    PM10 = 1
    CO2 = 2
    TVOC = 3
    ILLUMINANCE = 4
    TIME = 5
    CYCLE = 6


class Rs485Protocol(IntEnum):
    MODBUS = 0
    CUNET = 1


@dataclass(frozen=True)
class ThresholdTriplet:
    """Observed words, not app-valid edits; exact ranges/equality remain unresolved."""

    low: int | None
    mid: int | None
    high: int | None
    unit: str

    @property
    def ordered(self) -> bool | None:
        if not all(is_word(value) for value in (self.low, self.mid, self.high)):
            return None
        return self.low <= self.mid <= self.high


@dataclass(frozen=True)
class Selection:
    raw: int | None
    mode: IntEnum | None
    quality: Quality


@dataclass(frozen=True)
class NumericSetting:
    raw: int | None
    value: int | None
    quality: Quality


@dataclass(frozen=True)
class DisplaySettings:
    brightness_slider: NumericSetting
    illuminance_threshold: NumericSetting
    primary: Selection
    secondary: Selection


@dataclass(frozen=True)
class Compensation:
    raw: int | None
    temperature_code: int | None
    humidity_code: int | None
    temperature_tenths: int | None
    humidity_tenths: int | None
    quality: Quality


@dataclass(frozen=True)
class AqmSettings:
    pm25: ThresholdTriplet
    pm10: ThresholdTriplet
    co2: ThresholdTriplet
    tvoc: ThresholdTriplet
    backlight: Selection
    display: DisplaySettings
    rs485_protocol: Selection
    rs485_id: NumericSetting
    compensation: Compensation


def _quality(raw: int | None) -> Quality:
    return "missing" if raw is None else "valid" if is_word(raw) else "invalid"


def _selection(raw: int | None, enum: type[IntEnum] | None) -> Selection:
    quality = _quality(raw)
    if quality != "valid":
        return Selection(raw, None, quality)
    if enum is not None:
        try:
            return Selection(raw, enum(raw), "valid")
        except ValueError:
            pass
    return Selection(raw, None, "unknown")


def _numeric(raw: int | None, *, known: bool = True) -> NumericSetting:
    quality = _quality(raw)
    if quality != "valid":
        return NumericSetting(raw, None, quality)
    return NumericSetting(raw, raw if known else None, "valid" if known else "unknown")


def decode_compensation(raw: int | None) -> Compensation:
    """Decode every wire byte, including special zero and out-of-guide codes."""
    if not is_word(raw):
        return Compensation(raw, None, None, None, None, _quality(raw))
    temperature, humidity = raw & 0xFF, raw >> 8
    return Compensation(raw, temperature, humidity, temperature - 50 if temperature else 0,
                        humidity - 100 if humidity else 0, "valid")


def decode_settings(registers: Sequence[int | None], *, display: Literal["fnd", "lcd"] | None) -> AqmSettings:
    """Compose settings from the same read input, using existing AQM metadata display meaning."""
    def raw(index: int) -> int | None:
        return registers[index] if index < len(registers) else None

    brightness = _numeric(raw(23), known=False)
    if display == "fnd" and is_word(raw(23)) and raw(23) <= 15:
        brightness = NumericSetting(raw(23), 15 - raw(23), "valid")
    return AqmSettings(
        ThresholdTriplet(raw(10), raw(11), raw(12), "μg/m³"),
        ThresholdTriplet(raw(13), raw(14), raw(15), "μg/m³"),
        ThresholdTriplet(raw(16), raw(17), raw(18), "ppm"),
        ThresholdTriplet(raw(19), raw(20), raw(21), "ppb"),
        _selection(raw(22), BacklightMode),
        DisplaySettings(brightness, _numeric(raw(23), known=display == "lcd"),
                        _selection(raw(24), FndPrimary if display == "fnd" else LcdPrimary if display == "lcd" else None),
                        _selection(raw(25), FndSecondary if display == "fnd" else None)),
        _selection(raw(27), Rs485Protocol),
        _numeric(raw(28)),
        decode_compensation(raw(29)),
    )


def encode_thresholds(low: int, mid: int, high: int) -> tuple[int, int, int]:
    """Validate wire words/order only; equality and app ranges are NOT qualified."""
    values = (low, mid, high)
    if not all(is_word(value) for value in values) or not low <= mid <= high:
        raise ValueError("Thresholds require ordered unsigned words")
    return values


def encode_backlight(mode: BacklightMode) -> int:
    if type(mode) is not BacklightMode:
        raise ValueError("A known backlight mode is required")
    return int(mode)


def encode_brightness(slider: int, *, display: Literal["fnd", "lcd"] | None) -> int:
    if display != "fnd" or type(slider) is not int or not 0 <= slider <= 15:
        raise ValueError("FND brightness requires an integer slider in 0..15")
    return 15 - slider


def encode_display_selection(mode: IntEnum, *, display: Literal["fnd", "lcd"] | None, register: int) -> int:
    expected = {("fnd", 24): FndPrimary, ("fnd", 25): FndSecondary, ("lcd", 24): LcdPrimary}.get((display, register))
    if expected is None or type(mode) is not expected:
        raise ValueError("A known selection for this display/register is required")
    return int(mode)


def encode_rs485_protocol(mode: Rs485Protocol) -> int:
    if type(mode) is not Rs485Protocol:
        raise ValueError("A known RS485 protocol is required")
    return int(mode)


def encode_rs485_id(value: int) -> int:
    """App input range only, not Modbus address or physical support validation."""
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("RS485 app input requires an integer in 0..255")
    return value


def compensation_tenths(value: int | float | Decimal) -> int:
    """Normalize a semantic value exactly to tenths, without binary truncation."""
    if type(value) not in (int, float, Decimal):
        raise ValueError("Compensation requires a numeric value in exact 0.1 steps")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Compensation must be finite")
    numerator, denominator = number.as_integer_ratio()
    tenths, remainder = divmod(numerator * 10, denominator)
    if remainder:
        raise ValueError("Compensation requires exact 0.1 steps")
    return tenths


def _code(tenths: int, minimum: int, maximum: int, offset: int) -> int:
    if type(tenths) is not int or not minimum <= tenths <= maximum:
        raise ValueError(f"Compensation requires integer tenths in {minimum}..{maximum}")
    return tenths + offset


def encode_compensation(temperature_tenths: int, humidity_tenths: int) -> int:
    """Canonical semantic encoding; zero/zero is 0x6432, not raw-zero replay."""
    return _code(temperature_tenths, -49, 50, 50) | (_code(humidity_tenths, -99, 100, 100) << 8)


def encode_temperature(original: int, temperature_tenths: int) -> int:
    """Pure word composition; retain the original humidity byte exactly."""
    if not is_word(original):
        raise ValueError("A valid original compensation word is required")
    return (original & 0xFF00) | _code(temperature_tenths, -49, 50, 50)


def encode_humidity(original: int, humidity_tenths: int) -> int:
    """Pure word composition; retain the original temperature byte exactly."""
    if not is_word(original):
        raise ValueError("A valid original compensation word is required")
    return (original & 0x00FF) | (_code(humidity_tenths, -99, 100, 100) << 8)
