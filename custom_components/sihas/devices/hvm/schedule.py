"""Offline HVM 3.33 schedule codecs; no room attribution, I/O or capabilities.

Raw pairs remain exact. pack_* reconstructs bit-representable fields, including
out-of-guide values; encode_* additionally validates app-facing input. Neither
path qualifies hardware. No BCM layout or common numeric scale is reused.
"""
from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Literal

Version = tuple[int | None, int | None] | None
RawPair = tuple[int | None, int | None]
_PERIODIC_ADDRESSES = (50, 28)  # Bank numbers are not room numbers.


def _integer(value: int | None, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _require(value: int, lower: int, upper: int, field: str) -> None:
    if not _integer(value, lower, upper):
        raise ValueError(f"Invalid {field}: {value}")


def _flag(value: bool, field: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"Invalid {field}: {value}")


def supports_firmware(version: Version) -> bool:
    """This module's supported window, not a claim of physical schedule support.

    The periodic selection is evidenced at major3/minor>=30. DefaultSchedule is
    conservatively exposed within this same task window, not claimed to originate
    at 3.30 or extended to unqualified older/other firmware.
    """
    return (isinstance(version, tuple) and len(version) == 2 and type(version[0]) is int
            and version[0] == 3 and type(version[1]) is int and version[1] >= 30)


def _require_firmware(version: Version) -> None:
    if not supports_firmware(version):
        raise ValueError("Unqualified HVM schedule firmware")


@dataclass(frozen=True)
class SlotTime:
    kind: Literal["date", "day"]
    repeat: bool
    hour: int
    minute: int
    enabled: bool
    month: int | None = None
    day: int | None = None
    weekdays: int | None = None


@dataclass(frozen=True)
class SlotSetting:
    override: bool
    value_code: int
    temperature_control: bool
    run: bool

    @property
    def mode(self) -> Literal["stop", "temperature", "time"]:
        return "stop" if not self.run else "temperature" if self.temperature_control else "time"

    @property
    def preserve_value(self) -> bool:
        """Stored-value selection, not the independent run/stop or enable state."""
        return not self.override or self.value_code == 0

    @property
    def temperature_celsius(self) -> float | None:
        """Nonzero field conversion, not an applied target when override/run is false."""
        return self.value_code * 0.5 if self.temperature_control and self.value_code != 0 else None

    @property
    def time_minutes(self) -> int | None:
        """Raw TIME minutes, never periodic five-minute units."""
        return None if self.temperature_control or self.value_code == 0 else self.value_code


@dataclass(frozen=True)
class DefaultSlot:
    raw: RawPair
    time: SlotTime | None
    setting: SlotSetting | None
    unknown_a_bits: int | None


def decode_slot(a: int | None, b: int | None, version: Version) -> DefaultSlot:
    if not supports_firmware(version) or not _integer(a, 0, 65535) or not _integer(b, 0, 65535):
        return DefaultSlot((a, b), None, None, None)
    date = bool(a & 1)
    time = SlotTime("date" if date else "day", bool(a & 2), a >> 11, b & 63, bool(b & 0x8000),
                    (a >> 2) & 15 if date else None, (a >> 6) & 31 if date else None,
                    None if date else (a >> 4) & 127)
    setting = SlotSetting(bool(b & 64), (b >> 7) & 63, bool(b & 0x2000), bool(b & 0x4000))
    return DefaultSlot((a, b), time, setting, 0 if date else a & 12)


def decode_slots(registers: Sequence[int | None], version: Version) -> tuple[DefaultSlot, ...]:
    def word(index: int) -> int | None:
        return registers[index] if index < len(registers) else None

    return tuple(decode_slot(word(30 + index * 2), word(31 + index * 2), version) for index in range(10))


def pack_slot(time: SlotTime, setting: SlotSetting, version: Version, *, original_a: int = 0) -> tuple[int, int]:
    """Lossless field reconstruction, not app validation; preserves day A bits2..3."""
    _require_firmware(version)
    _require(original_a, 0, 65535, "original A")
    _require(time.hour, 0, 31, "hour bits")
    _require(time.minute, 0, 63, "minute bits")
    _require(setting.value_code, 0, 63, "value bits")
    for value, name in ((time.repeat, "repeat"), (time.enabled, "enabled"), (setting.override, "override"),
                        (setting.temperature_control, "temperature_control"), (setting.run, "run")):
        _flag(value, name)
    a = int(time.repeat) << 1 | time.hour << 11
    if time.kind == "date":
        _require(time.month, 0, 15, "month bits")
        _require(time.day, 0, 31, "day bits")
        if time.weekdays is not None:
            raise ValueError("Date fields cannot also specify weekdays")
        a |= 1 | time.month << 2 | time.day << 6
    elif time.kind == "day":
        _require(time.weekdays, 0, 127, "weekdays")
        if time.month is not None or time.day is not None:
            raise ValueError("Weekdays cannot also specify a date")
        a |= original_a & 12 | time.weekdays << 4
    else:
        raise ValueError("Unknown date/day kind")
    b = (time.minute | int(setting.override) << 6 | setting.value_code << 7 | int(setting.temperature_control) << 13
         | int(setting.run) << 14 | int(time.enabled) << 15)
    return a, b


def encode_slot(time: SlotTime, setting: SlotSetting, version: Version, *, original_a: int = 0) -> tuple[int, int]:
    """App input validation without silently clearing stored flags or values.

    STOP skips setting validation, as the app does. TIME/TEMP retain their raw
    independent flags; use time_setting/temperature_setting for the evidenced
    zero-input edit behavior that clears override and value.
    """
    _require_firmware(version)
    _require(time.hour, 0, 23, "hour")
    _require(time.minute, 0, 59, "minute")
    if time.kind == "date":
        _require(time.month, 1, 12, "month")
        _require(time.day, 1, 31, "day")
        if time.day > (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[time.month - 1]:
            raise ValueError("Invalid month/day; no year is inferred")
    if setting.run:
        if setting.temperature_control:
            if setting.value_code != 0 and not _integer(setting.value_code, 20, 60):
                raise ValueError("App TEMP input requires preserve0 or 10..30 Celsius")
        elif setting.value_code not in (0, 10, 20, 30, 40, 50):
            raise ValueError("App TIME input requires preserve0 or 10/20/30/40/50 minutes")
    return pack_slot(time, setting, version, original_a=original_a)


def temperature_setting(celsius: float | None) -> SlotSetting:
    """Exact six-bit half-degree conversion; zero/empty input clears override.

    Representability (0..31.5) is separate from encode_slot's app 10..30 guide.
    No rounding/truncation is performed and no physical range is asserted.
    """
    if celsius is None:
        return SlotSetting(False, 0, True, True)
    if type(celsius) not in (int, float) or not math.isfinite(celsius) or not 0 <= celsius <= 31.5 or (celsius * 2) % 1:
        raise ValueError("Temperature is not an exact six-bit half-degree value")
    code = int(celsius * 2)
    return SlotSetting(code != 0, code, True, True)


def time_setting(minutes: int | None) -> SlotSetting:
    """TIME uses integer minutes; zero/empty clears override as the app editor does."""
    if minutes is None:
        return SlotSetting(False, 0, False, True)
    _require(minutes, 0, 63, "TIME minutes")
    return SlotSetting(minutes != 0, minutes, False, True)


def edit_slot(registers: Sequence[int | None], index: int, time: SlotTime, setting: SlotSetting,
              version: Version) -> tuple[int | None, ...]:
    _require(index, 0, 9, "slot index")
    start = 30 + index * 2
    if len(registers) < 50 or not all(_integer(word, 0, 65535) for word in registers[start:start + 2]):
        raise ValueError("A complete schedule prefix and valid original pair are required")
    pair = encode_slot(time, setting, version, original_a=registers[start])
    result = list(registers)
    result[start:start + 2] = pair
    return tuple(result)


@dataclass(frozen=True)
class PeriodicFields:
    enabled: bool
    weekdays: int
    start_hour: int
    end_hour: int
    period_hours: int
    on_minutes: int
    active_temperature: int | Literal["preserve"]
    end_action: int | Literal["off"]  # Action at interval end, not between ON cycles.


@dataclass(frozen=True)
class PeriodicRepeat:
    raw: RawPair
    fields: PeriodicFields | None
    # All 32 bits are accounted for in this HVM layout; bit15 is not BCM's unknown bit.


def decode_periodic(a: int | None, b: int | None, version: Version) -> PeriodicRepeat:
    if not supports_firmware(version) or not _integer(a, 0, 65535) or not _integer(b, 0, 65535):
        return PeriodicRepeat((a, b), None)
    active, end = (b >> 8) & 15, b >> 12
    fields = PeriodicFields(bool(a & 1), (a >> 1) & 127, (a >> 8) & 31, (a >> 13) | ((b & 3) << 3),
                            ((b >> 2) & 3) + 1, (((b >> 4) & 15) + 1) * 5,
                            "preserve" if active == 0 else active + 15, "off" if end == 0 else end + 15)
    return PeriodicRepeat((a, b), fields)


def pack_periodic(fields: PeriodicFields, version: Version) -> tuple[int, int]:
    """Reconstruct all 32 bits. There is no evidenced unknown-bit clearing step."""
    _require_firmware(version)
    _flag(fields.enabled, "enabled")
    for value, lower, upper, name in (
        (fields.weekdays, 0, 127, "weekdays"), (fields.start_hour, 0, 31, "start bits"),
        (fields.end_hour, 0, 31, "end bits"), (fields.period_hours, 1, 4, "period hours"),
        (fields.on_minutes, 5, 80, "ON minutes"),
    ):
        _require(value, lower, upper, name)
    if fields.on_minutes % 5:
        raise ValueError("Periodic ON time requires five-minute units")
    if fields.active_temperature == "preserve":
        active = 0
    else:
        _require(fields.active_temperature, 16, 30, "active temperature")
        active = fields.active_temperature - 15
    if fields.end_action == "off":
        end = 0
    else:
        _require(fields.end_action, 16, 30, "end temperature")
        end = fields.end_action - 15
    a = int(fields.enabled) | fields.weekdays << 1 | fields.start_hour << 8 | (fields.end_hour & 7) << 13
    b = fields.end_hour >> 3 | (fields.period_hours - 1) << 2 | (fields.on_minutes // 5 - 1) << 4 | active << 8 | end << 12
    return a, b


def encode_periodic(fields: PeriodicFields, version: Version) -> tuple[int, int]:
    """Validate clock input; crossing/equal endpoints do not assert execution behavior."""
    _require(fields.start_hour, 0, 24, "start hour")
    _require(fields.end_hour, 0, 24, "end hour")
    return pack_periodic(fields, version)


def decode_periodic_banks(registers: Sequence[int | None], version: Version) -> tuple[PeriodicRepeat, ...]:
    def word(index: int) -> int | None:
        return registers[index] if index < len(registers) else None

    return tuple(decode_periodic(word(start), word(start + 1), version) for start in _PERIODIC_ADDRESSES)


def edit_periodic_bank(registers: Sequence[int | None], bank: int, fields: PeriodicFields,
                       version: Version) -> tuple[int | None, ...]:
    """Edit pair0 R50/R51 or pair1 R28/R29, with no inferred room/selector context."""
    _require(bank, 0, 1, "periodic bank")
    start = _PERIODIC_ADDRESSES[bank]
    if len(registers) < start + 2 or not all(_integer(word, 0, 65535) for word in registers[start:start + 2]):
        raise ValueError("A complete valid original bank pair is required")
    pair = encode_periodic(fields, version)
    result = list(registers)
    result[start:start + 2] = pair
    return tuple(result)
