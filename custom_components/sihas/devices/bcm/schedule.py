"""Offline BCM schedule codecs from SiHAS 1.8.23 app-static evidence.

Decoded raw pairs are lossless, including missing/invalid words and unknown versions.
Encoders validate new field values; they never normalize a decoded raw pair in place.
`schedule_format` is the only firmware-version decision; codecs receive its prepared
layout. No function performs I/O, selects a controller, or qualifies a definition command.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .. import controls

if TYPE_CHECKING:
    from .state import BcmHotWaterRange

Version = tuple[int | None, int | None] | None
Format = Literal["old", "new"]
Mode = Literal["hot_water", "away", "bath", "timer", "room", "ondol"]
RawPair = tuple[int | None, int | None]
_MODE_CODES = {"hot_water": 0, "away": 0, "bath": 0, "timer": 1, "room": 2, "ondol": 3}


def _integer(value: int | None, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _require(value: int, minimum: int, maximum: int, field: str) -> None:
    if not _integer(value, minimum, maximum):
        raise ValueError(f"Invalid {field}: {value}")


def _flag(value: bool, field: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"Invalid {field}: {value}")


def schedule_format(version: Version) -> Format | None:
    """Only major 2/3 are qualified for layout selection, not physical operation.

    Callers resolve this once when preparing a runtime or an offline context.
    """
    if not isinstance(version, tuple) or len(version) != 2:
        return None
    major, minor = version
    if type(major) is not int or type(minor) is not int or minor < 0:
        return None
    if major == 2:
        return "new" if minor >= 20 else "old"
    return "new" if major == 3 else None


@dataclass(frozen=True)
class SlotTime:
    kind: Literal["date", "day"]
    repeat: bool
    hour: int
    minute: int
    enabled: bool
    month: int | None = None
    day: int | None = None
    weekdays: int | None = None  # Sunday bit0 through Saturday bit6.


@dataclass(frozen=True)
class OldSetting:
    select_setpoint: bool
    temperature: int
    home: bool  # Explicit bit14; never inferred from temperature.


@dataclass(frozen=True)
class NewSetting:
    mode: Mode
    parameter: int  # Encoded p, not a direct R3 value or an R7 word.

    @property
    def preserve_value(self) -> bool:
        return self.parameter == 0


@dataclass(frozen=True)
class ScheduleSlot:
    raw: RawPair
    format: Format | None
    time: SlotTime | None
    setting: OldSetting | NewSetting | None
    unknown_a_bits: int | None


def decode_slot(a: int | None, b: int | None, layout: Format | None) -> ScheduleSlot:
    """Preserve raw exactly; an unqualified (None) layout keeps common time fields without a guessed B setting."""
    if not _integer(a, 0, 65535) or not _integer(b, 0, 65535):
        return ScheduleSlot((a, b), layout, None, None, None)
    date = bool(a & 1)
    time = SlotTime("date" if date else "day", bool(a & 2), a >> 11, b & 63, bool(b & 0x8000),
                    (a >> 2) & 15 if date else None, (a >> 6) & 31 if date else None,
                    None if date else (a >> 4) & 127)
    setting = None
    if layout == "old":
        setting = OldSetting(bool(b & 64), (b >> 7) & 127, bool(b & 0x4000))
    elif layout == "new":
        code, parameter = (b >> 13) & 3, (b >> 6) & 127
        mode = ("hot_water", "timer", "room", "ondol")[code]
        if code == 0 and parameter in (88, 99):
            mode = "bath" if parameter == 88 else "away"
        setting = NewSetting(mode, parameter)
    return ScheduleSlot((a, b), layout, time, setting, 0 if date else a & 12)


def decode_slots(registers: Sequence[int | None], layout: Format | None) -> tuple[ScheduleSlot, ...]:
    """Read all ten pairs without padding a missing snapshot with zero words."""
    def word(index: int) -> int | None:
        return registers[index] if index < len(registers) else None

    return tuple(decode_slot(word(30 + 2 * index), word(31 + 2 * index), layout) for index in range(10))


_SLOT_ENABLED = 0x8000
_INTERVAL_ENABLED = 0x0001


def slot_toggle(index: int, slot: ScheduleSlot) -> controls.StoredToggle | None:
    """B-word bit15 enable of general slot `index` (R31 + 2 * index) over its exact raw pair.

    The bit is common to both schedule layouts; decoding the setting is not required.
    A slot with no bit other than bit15 set is an empty slot.
    """
    _require(index, 0, 9, "slot index")
    return controls.stored_toggle(31 + 2 * index, slot.raw, 1, _SLOT_ENABLED,
                                  populated=lambda words: controls.non_enable_bits_set(words, 1, _SLOT_ENABLED))


def interval_toggle(interval: IntervalRepeat) -> controls.StoredToggle | None:
    """R50 bit0 interval-repeat enable over the exact R50/R51 pair; R51 bit15 is not an enable.

    No BCM evidence qualifies an all-zero pair as a configured interval, so it remains empty storage.
    """
    return controls.stored_toggle(50, interval.raw, 0, _INTERVAL_ENABLED,
                                  populated=lambda words: controls.non_enable_bits_set(words, 0, _INTERVAL_ENABLED))


def encode_slot(time: SlotTime, setting: OldSetting | NewSetting, layout: Format | None, *, original_a: int = 0) -> tuple[int, int]:
    """Construct a validated pair, retaining day-type unknown A bits2..3.

    Type changes replace the overlapping bits4..10 explicitly. Switching to date
    also replaces bits2..3 with month bits; switching to day retains their raw bits.
    This is field encoding, not mutable device-range validation or write permission.
    """
    if layout not in ("old", "new"):
        raise ValueError("BCM schedule layout is unqualified")
    _require(original_a, 0, 65535, "original A")
    _require(time.hour, 0, 23, "hour")
    _require(time.minute, 0, 59, "minute")
    _flag(time.repeat, "repeat")
    _flag(time.enabled, "enabled")
    a = int(time.repeat) << 1 | time.hour << 11
    if time.kind == "date":
        _require(time.month, 1, 12, "month")
        _require(time.day, 1, 31, "day")
        if time.weekdays is not None:
            raise ValueError("Date encoding cannot also specify weekdays")
        # No year is encoded; February 29 is representable without asserting a leap year.
        if time.day > (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[time.month - 1]:
            raise ValueError("Invalid month/day combination")
        a |= 1 | time.month << 2 | time.day << 6
    elif time.kind == "day":
        _require(time.weekdays, 0, 127, "weekdays")
        if time.month is not None or time.day is not None:
            raise ValueError("Weekday encoding cannot also specify a date")
        a |= original_a & 12 | time.weekdays << 4
    else:
        raise ValueError("Unknown schedule date/day type")
    b = time.minute | int(time.enabled) << 15
    if layout == "old" and isinstance(setting, OldSetting):
        _flag(setting.select_setpoint, "select_setpoint")
        _flag(setting.home, "home")
        _require(setting.temperature, 0, 127, "temperature")
        b |= int(setting.select_setpoint) << 6 | setting.temperature << 7 | int(setting.home) << 14
    elif layout == "new" and isinstance(setting, NewSetting):
        _require(setting.parameter, 0, 127, "parameter")
        code = _MODE_CODES.get(setting.mode)
        if code is None or setting.mode == "away" and setting.parameter != 99 or setting.mode == "bath" and setting.parameter != 88:
            raise ValueError("Unknown or inconsistent schedule mode")
        if setting.mode == "hot_water" and setting.parameter in (88, 99):
            raise ValueError("Use explicit bath/away mode for special hot-water parameters")
        b |= code << 13 | setting.parameter << 6
    else:
        raise ValueError("Setting does not match the selected schedule generation")
    return a, b


def edit_slot(registers: Sequence[int | None], index: int, time: SlotTime, setting: OldSetting | NewSetting,
              layout: Format | None) -> tuple[int | None, ...]:
    """Return a copy with only the selected slot changed; this is not a packet builder."""
    _require(index, 0, 9, "slot index")
    start = 30 + index * 2
    if len(registers) < 50 or not all(_integer(value, 0, 65535) for value in registers[start:start + 2]):
        raise ValueError("Editing requires the complete schedule bank and a valid original pair")
    a, b = encode_slot(time, setting, layout, original_a=registers[start])
    result = list(registers)
    result[start:start + 2] = a, b
    return tuple(result)


def decode_hot_water_level(parameter: int, bounds: BcmHotWaterRange) -> str | None:
    """Scheduled levels are 1-based; zero preserves and 88/99 are separate modes."""
    levels = bounds.levels
    if levels is None or not _integer(parameter, 1, len(levels)):
        return None
    return levels[parameter - 1]


def encode_hot_water_level(level: str, bounds: BcmHotWaterRange) -> int:
    """Encode semantic labels, never direct R3 integers or OFF."""
    levels = bounds.levels
    if levels is None or level not in levels:
        raise ValueError("Unknown scheduled hot-water level or range")
    return levels.index(level) + 1


def decode_timer_parameter(parameter: int) -> tuple[int, int] | None:
    """Return raw normal components; zero is preserve, not zero-hour operation.

    Raw components outside the app's 1..6h / 10,20,30m guide are retained as codec
    observations only. They are not physical support or app-guided settings.
    """
    _require(parameter, 0, 127, "parameter")
    return None if parameter == 0 else (parameter // 10, (parameter % 10) * 10)


def encode_timer_parameter(period_hours: int, run_minutes: int) -> int:
    """App-guided schedule parameter, intentionally distinct from the R7 codec."""
    _require(period_hours, 1, 6, "period_hours")
    if type(run_minutes) is not int or run_minutes not in (10, 20, 30):
        raise ValueError("Schedule timer requires 10, 20 or 30 run minutes")
    return period_hours * 10 + run_minutes // 10


@dataclass(frozen=True)
class IntervalFields:
    enabled: bool
    weekdays: int
    start_hour: int
    end_hour: int
    period_hours: int
    run_minutes: int
    temperature_control: bool


@dataclass(frozen=True)
class IntervalRepeat:
    raw: RawPair
    fields: IntervalFields | None
    unknown_bits: int | None  # R51 bit15; never interval enable or a guessed mode.


def decode_interval(a: int | None, b: int | None) -> IntervalRepeat:
    """Decode raw fields even outside app input bounds; retain unknown bit15."""
    if not _integer(a, 0, 65535) or not _integer(b, 0, 65535):
        return IntervalRepeat((a, b), None, None)
    fields = IntervalFields(bool(a & 1), (a >> 1) & 127, (a >> 8) & 31,
                            (a >> 13) | ((b & 3) << 3), (b >> 8) & 63, (b >> 2) & 63, bool(b & 0x4000))
    return IntervalRepeat((a, b), fields, b & 0x8000)


def encode_interval(fields: IntervalFields, *, unknown_bits: int = 0) -> tuple[int, int]:
    """Validate app storage bounds while preserving explicitly supplied unknown bits.

    61..63 minutes are codec/storage-representable, not app-guided (1..60) or
    physically qualified. Midnight crossing and equal endpoints encode without
    claiming their execution, timezone, priority or repeat behavior.
    """
    _flag(fields.enabled, "enabled")
    _flag(fields.temperature_control, "temperature_control")
    for value, lower, upper, name in (
        (fields.weekdays, 0, 127, "weekdays"), (fields.start_hour, 0, 24, "start_hour"),
        (fields.end_hour, 0, 24, "end_hour"), (fields.period_hours, 1, 12, "period_hours"),
        (fields.run_minutes, 1, 63, "run_minutes"),
    ):
        _require(value, lower, upper, name)
    if type(unknown_bits) is not int or unknown_bits not in (0, 0x8000):
        raise ValueError("Only R51 bit15 is unknown")
    a = int(fields.enabled) | fields.weekdays << 1 | fields.start_hour << 8 | (fields.end_hour & 7) << 13
    b = fields.end_hour >> 3 | fields.run_minutes << 2 | fields.period_hours << 8 | int(fields.temperature_control) << 14
    return a, b | unknown_bits


def encode_interval_canonical(fields: IntervalFields) -> tuple[int, int]:
    """App-compatible reconstruction explicitly clears R51 bit15."""
    return encode_interval(fields)


def interval_run_is_app_guided(run_minutes: int) -> bool:
    """The app's 1..60 minute guide is narrower than its 1..63 storage validator."""
    return _integer(run_minutes, 1, 60)
