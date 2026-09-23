"""BCM app-static settings observations and offline codecs, without write qualification."""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
from typing import Literal

Quality = Literal["valid", "unknown", "missing", "invalid"]


class Backlight(IntEnum):
    AUTO_OFF = 0
    ON_OFF = 1
    ALWAYS_OFF = 2
    ALWAYS_ON = 3


class TouchLock(IntEnum):
    UNLOCKED = 0
    TEMPERATURE = 1
    FULL = 2


class Buzzer(IntEnum):
    DISABLED = 0
    ENABLED = 1


def _quality(raw: int | None) -> Quality:
    return "missing" if raw is None else "valid" if type(raw) is int and 0 <= raw <= 65535 else "invalid"


@dataclass(frozen=True)
class Selection:
    raw: int | None
    mode: IntEnum | None
    quality: Quality


def _selection(raw: int | None, enum: type[IntEnum]) -> Selection:
    quality = _quality(raw)
    if quality != "valid":
        return Selection(raw, None, quality)
    return Selection(raw, enum(raw), "valid") if raw in enum else Selection(raw, None, "unknown")


def decode_backlight(raw: int | None) -> Selection:
    return _selection(raw, Backlight)


def decode_touch_lock(raw: int | None) -> Selection:
    return _selection(raw, TouchLock)


def decode_buzzer(raw: int | None) -> Selection:
    return _selection(raw, Buzzer)


def _encode(mode: IntEnum, enum: type[IntEnum]) -> int:
    if type(mode) is not enum:
        raise ValueError(f"Expected a known {enum.__name__} option")
    return int(mode)


def encode_backlight(mode: Backlight) -> int:
    return _encode(mode, Backlight)


def encode_touch_lock(mode: TouchLock) -> int:
    return _encode(mode, TouchLock)


def encode_buzzer(mode: Buzzer) -> int:
    return _encode(mode, Buzzer)


@dataclass(frozen=True)
class Compensation:
    raw: int | None
    tenths: int | None
    quality: Quality

    @property
    def value(self) -> Decimal | None:
        if self.tenths is None:
            return None
        magnitude = abs(self.tenths)
        return Decimal(f"{'-' if self.tenths < 0 else ''}{magnitude // 10}.{magnitude % 10}")

    @property
    def within_guide(self) -> bool | None:
        return -50 <= self.tenths <= 50 if self.tenths is not None else None


def decode_compensation(raw: int | None) -> Compensation:
    quality = _quality(raw)
    return Compensation(raw, raw - 50 if quality == "valid" else None, quality)


def compensation_tenths(value: int | float | Decimal) -> int:
    """Accept exact finite 0.1 steps in the app guide, without float truncation."""
    if type(value) not in (int, float, Decimal):
        raise ValueError("Compensation requires a numeric value")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Compensation must be finite")
    numerator, denominator = number.as_integer_ratio()
    tenths, remainder = divmod(numerator * 10, denominator)
    if remainder or not -50 <= tenths <= 50:
        raise ValueError("Compensation requires exact 0.1 steps in -5..5")
    return tenths


def encode_compensation(tenths: int) -> int:
    """Canonical exact-tenths input; raw out-of-guide observations stay untouched."""
    if type(tenths) is not int or not -50 <= tenths <= 50:
        raise ValueError("Compensation requires integer tenths in -50..50")
    return tenths + 50


@dataclass(frozen=True)
class BcmSettings:
    backlight: Selection
    compensation: Compensation
    touch_lock: Selection
    buzzer: Selection


def decode_settings(registers: Sequence[int | None]) -> BcmSettings:
    raw = [registers[index] if index < len(registers) else None for index in (17, 18, 52, 62)]
    return BcmSettings(decode_backlight(raw[0]), decode_compensation(raw[1]), decode_touch_lock(raw[2]), decode_buzzer(raw[3]))
