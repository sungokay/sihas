"""Pure AQM link codecs and passive observations of one selected bank.

App-static packing is not physical write qualification. Calendar interpretation,
notification enum names, target wire types and period-zero behavior stay unknown.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .metadata import Quality
from .metadata import is_word


def _integer(value: int, maximum: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} requires an integer in 0..{maximum}")
    return value


def selector_value(index: int) -> int:
    """Validate an offline selector value; never select a device bank."""
    return _integer(index, 9, "Link selector")


@dataclass(frozen=True)
class Event:
    raw: int

    @property
    def event_type(self) -> int:
        return self.raw & 0xFF

    @property
    def period_code(self) -> int:
        return self.raw >> 8

    @property
    def period_seconds(self) -> int:
        """Arithmetic only: code zero's firmware behavior is unresolved."""
        code = self.period_code
        return code * 10 if code <= 60 else (code - 50) * 60


def decode_event(raw: int) -> Event:
    return Event(_integer(raw, 0xFFFF, "Event word"))


def pack_event(event_type: int, period_code: int) -> int:
    return _integer(event_type, 255, "Event type") | (_integer(period_code, 255, "Period code") << 8)


# Paired >= / <= event codes, with link-edit guidance only (not sensor limits).
_CONDITIONS = (
    ("temperature", "°C", 10, 500), ("humidity", "%", 10, 1000),
    ("co2", "ppm", 1, 30000), ("pm25", "μg/m³", 1, 30000),
    ("pm10", "μg/m³", 1, 30000), ("tvoc", "ppb", 1, 30000), ("illuminance", "lx", 1, 30000),
)


@dataclass(frozen=True)
class Condition:
    raw: int
    sensor: str | None
    comparison: str | None
    unit: str | None
    scale: int | None

    @property
    def value(self) -> int | Decimal | None:
        if self.scale is None:
            return None
        return Decimal(self.raw) / 10 if self.scale == 10 else self.raw


def decode_condition(event_type: int, raw: int) -> Condition:
    _integer(event_type, 255, "Event type")
    _integer(raw, 0xFFFF, "Condition word")
    if not 1 <= event_type <= 14:
        return Condition(raw, None, None, None, None)
    sensor, unit, scale, _ = _CONDITIONS[(event_type - 1) // 2]
    return Condition(raw, sensor, ">=" if event_type % 2 else "<=", unit, scale)


def condition_tenths(value: int | float | Decimal) -> int:
    """Normalize exact 0.1 steps, without binary-float truncation or rounding."""
    if type(value) not in (int, float, Decimal):
        raise ValueError("Link condition requires a numeric value in exact 0.1 steps")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Link condition must be finite")
    numerator, denominator = number.as_integer_ratio()
    tenths, remainder = divmod(numerator * 10, denominator)
    if remainder:
        raise ValueError("Link condition requires exact 0.1 steps")
    return tenths


def encode_condition(event_type: int, value: int) -> int:
    """App-guided input: integer tenths for temperature/humidity, units otherwise.

    Raw round-trips use the original word, not this edit validator. Unset/unknown
    events have no semantic encoder. A valid result never qualifies a writer.
    """
    _integer(event_type, 255, "Event type")
    if not 1 <= event_type <= 14:
        raise ValueError("A known condition event is required")
    return _integer(value, _CONDITIONS[(event_type - 1) // 2][3], "Link condition")


@dataclass(frozen=True)
class Notifications:
    raw: int

    @property
    def push(self) -> int:
        return self.raw & 1

    @property
    def lamp(self) -> int:
        return (self.raw >> 1) & 7

    @property
    def sound(self) -> int:
        return (self.raw >> 4) & 15

    @property
    def repeat(self) -> int:
        return self.raw >> 8


def decode_notifications(raw: int) -> Notifications:
    return Notifications(_integer(raw, 0xFFFF, "Notification word"))


def pack_notifications(*, push: int, lamp: int, sound: int, repeat: int) -> int:
    return (_integer(push, 1, "Push bit") | (_integer(lamp, 7, "Lamp field") << 1)
            | (_integer(sound, 15, "Sound field") << 4) | (_integer(repeat, 255, "Repeat field") << 8))


def edit_notifications(raw: int, *, push: int | None = None, lamp: int | None = None,
                       sound: int | None = None, repeat: int | None = None) -> int:
    """Replace specified numeric fields, preserving every other bit."""
    current = decode_notifications(raw)
    return pack_notifications(push=current.push if push is None else push, lamp=current.lamp if lamp is None else lamp,
                              sound=current.sound if sound is None else sound, repeat=current.repeat if repeat is None else repeat)


def decode_mac(words: Sequence[int]) -> bytes:
    if len(words) != 3:
        raise ValueError("Link MAC requires exactly three words")
    return b"".join(_integer(word, 0xFFFF, "MAC word").to_bytes(2, "big") for word in words)


def pack_mac(mac: Sequence[int]) -> tuple[int, int, int]:
    if len(mac) != 6:
        raise ValueError("Link MAC requires exactly six bytes")
    octets = tuple(_integer(value, 255, "MAC byte") for value in mac)
    return tuple(octets[index] * 256 + octets[index + 1] for index in (0, 2, 4))


@dataclass(frozen=True)
class TimeCondition:
    raw: int

    @property
    def mode(self) -> int:
        return self.raw & 1

    @property
    def repeat(self) -> int:
        return (self.raw >> 1) & 1

    @property
    def weekday_or_date(self) -> int:
        return (self.raw >> 2) & 127

    @property
    def begin_hour(self) -> int:
        return (self.raw >> 9) & 31

    @property
    def begin_minute(self) -> int:
        return (self.raw >> 14) & 63

    @property
    def end_hour(self) -> int:
        return (self.raw >> 20) & 31

    @property
    def end_minute(self) -> int:
        return (self.raw >> 25) & 63

    @property
    def enabled(self) -> int:
        return self.raw >> 31

    @property
    def words(self) -> tuple[int, int]:
        return self.raw & 0xFFFF, self.raw >> 16


def decode_time(low: int, high: int) -> TimeCondition:
    return TimeCondition(_integer(low, 0xFFFF, "R60") | (_integer(high, 0xFFFF, "R61") << 16))


def pack_time(*, mode: int, repeat: int, weekday_or_date: int, begin_hour: int, begin_minute: int,
              end_hour: int, end_minute: int, enabled: int) -> tuple[int, int]:
    """Pack numeric fields only; no calendar or clock-range interpretation."""
    raw = (_integer(mode, 1, "Mode") | (_integer(repeat, 1, "Repeat") << 1)
           | (_integer(weekday_or_date, 127, "Weekday/date field") << 2)
           | (_integer(begin_hour, 31, "Begin hour") << 9) | (_integer(begin_minute, 63, "Begin minute") << 14)
           | (_integer(end_hour, 31, "End hour") << 20) | (_integer(end_minute, 63, "End minute") << 25)
           | (_integer(enabled, 1, "Enabled") << 31))
    return raw & 0xFFFF, raw >> 16


@dataclass(frozen=True)
class LinkBank:
    """Exactly R51–R61; target type and target payload have no inferred meaning."""

    event: Event
    condition_raw: int
    notifications: Notifications
    target_type_raw: int
    mac: bytes
    target_register: int
    target_value: int
    time: TimeCondition

    @property
    def condition(self) -> Condition:
        return decode_condition(self.event.event_type, self.condition_raw)


def decode_bank(words: Sequence[int]) -> LinkBank:
    if len(words) != 11 or not all(is_word(word) for word in words):
        raise ValueError("Link bank requires exactly eleven unsigned words")
    return LinkBank(decode_event(words[0]), words[1], decode_notifications(words[2]), words[3], decode_mac(words[4:7]),
                    words[7], words[8], decode_time(words[9], words[10]))


def pack_bank(bank: LinkBank) -> tuple[int, ...]:
    """Offline ordered words only, not a transport packet or write operation."""
    raw_time = _integer(bank.time.raw, 0xFFFFFFFF, "Time condition")
    words = (bank.event.raw, bank.condition_raw, bank.notifications.raw, bank.target_type_raw, *pack_mac(bank.mac),
             bank.target_register, bank.target_value, raw_time & 0xFFFF, raw_time >> 16)
    return tuple(_integer(word, 0xFFFF, "Bank word") for word in words)


def set_enabled(raw: int, index: int, enabled: bool) -> int:
    """Pure idempotent target state; preserve unrelated rule and unknown bits."""
    _integer(raw, 0xFFFF, "Enable mask")
    bit = 1 << selector_value(index)
    if type(enabled) is not bool:
        raise ValueError("Enable target state requires bool")
    return raw | bit if enabled else raw & ~bit


@dataclass(frozen=True)
class SelectedLink:
    """Current snapshot only; invalid/missing observations are never defaults."""

    selector_raw: int | None
    bank_raw: tuple[int | None, ...]
    enable_raw: int | None

    @property
    def selector_quality(self) -> Quality:
        if self.selector_raw is None:
            return "missing"
        if not is_word(self.selector_raw):
            return "invalid"
        return "valid" if self.selector_raw <= 9 else "unknown"

    @property
    def selected_index(self) -> int | None:
        return self.selector_raw if self.selector_quality == "valid" else None

    @property
    def bank(self) -> LinkBank | None:
        """Decode available raw data without attributing it to an invented index."""
        if len(self.bank_raw) != 11 or not all(is_word(word) for word in self.bank_raw):
            return None
        return decode_bank(self.bank_raw)

    @property
    def enabled_rules(self) -> tuple[bool, ...] | None:
        if not is_word(self.enable_raw):
            return None
        return tuple(bool(self.enable_raw & (1 << index)) for index in range(10))

    @property
    def unknown_enable_bits(self) -> int | None:
        return self.enable_raw & 0xFC00 if is_word(self.enable_raw) else None


def decode_selected_link(registers: Sequence[int | None]) -> SelectedLink:
    """Extract only the current window, never cache other banks or initiate I/O."""
    return SelectedLink(registers[50] if len(registers) > 50 else None, tuple(registers[51:62]),
                        registers[62] if len(registers) > 62 else None)
