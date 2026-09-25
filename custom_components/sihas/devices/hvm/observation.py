"""Pure HVM observations, qualified climate limits and offline intents.

One supplied snapshot contains one selected detail window. App-static semantics
and exact encodings do not qualify device writes, room attribution or hardware.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Literal

from . import schedule, summary

Quality = Literal["valid", "unknown", "missing", "invalid"]
_MODE = {0: "temperature", 1: "time", 2: "away"}
_DISPLAY = {0: "both", 1: "current", 2: "target", 3: "both"}
_BACKLIGHT = {0: "auto_off", 1: "on_off", 2: "always_off", 3: "always_on"}


# Exact firmware of the physically observed single-room installation that bounds the provisional controls.
CONTROL_FIRMWARE = (3, 33)


def firmware_version(firmware: str | None) -> tuple[int, int] | None:
    """Parse only recorded dotted integer components, never a numeric approximation."""
    match = re.fullmatch(r"V?([0-9]{1,2})\.([0-9]{1,3})", firmware) if isinstance(firmware, str) else None
    return (int(match[1]), int(match[2])) if match else None


def _quality(raw: int | None) -> Quality:
    return "missing" if raw is None else "valid" if type(raw) is int and 0 <= raw <= 65535 else "invalid"


@dataclass(frozen=True)
class Reading:
    raw: int | None
    value: int | float | bool | str | None
    quality: Quality


def _reading(raw: int | None) -> Reading:
    quality = _quality(raw)
    return Reading(raw, raw if quality == "valid" else None, quality)


def _choice(raw: int | None, choices: dict) -> Reading:
    quality = _quality(raw)
    if quality != "valid":
        return Reading(raw, None, quality)
    return Reading(raw, choices.get(raw), "valid" if raw in choices else "unknown")


def _flag(raw: int | None) -> Reading:
    quality = _quality(raw)
    return Reading(raw, raw != 0 if quality == "valid" else None, quality)


def _bounded(raw: int | None, low: int, high: int) -> Reading:
    result = _reading(raw)
    if result.quality == "valid" and not low <= raw <= high:
        return Reading(raw, None, "unknown")
    return result


@dataclass(frozen=True)
class Temperature:
    """Exact integer tenths; Decimal presentation is independent of its context."""

    raw: int | None
    tenths: int | None
    quality: Quality

    @property
    def celsius(self) -> Decimal | None:
        if self.tenths is None:
            return None
        magnitude = abs(self.tenths)
        return Decimal(f"{'-' if self.tenths < 0 else ''}{magnitude // 10}.{magnitude % 10}")


def _temperature(raw: int | None, *, offset: int = 0) -> Temperature:
    quality = _quality(raw)
    return Temperature(raw, raw - offset if quality == "valid" else None, quality)


@dataclass(frozen=True)
class Profile:
    """Mutable configuration observed at one instant, not hardware capabilities."""

    heating_type: Reading
    room_count: Reading
    homenet: Reading
    sez: Reading
    rs485_id: Reading
    summary_unit: Reading


@dataclass(frozen=True)
class Detail:
    selected_room: Reading
    power: Reading
    target: Temperature
    mode: Reading
    current: Temperature
    valve: Reading
    alarm: Reading
    on_minutes: Reading


@dataclass(frozen=True)
class Limits:
    upper: Reading
    lower: Reading

    @property
    def status(self) -> Literal["ordered", "equal", "reversed", "missing", "invalid"]:
        if "invalid" in (self.upper.quality, self.lower.quality):
            return "invalid"
        if "missing" in (self.upper.quality, self.lower.quality):
            return "missing"
        return "reversed" if self.lower.value > self.upper.value else "equal" if self.lower.value == self.upper.value else "ordered"


@dataclass(frozen=True)
class Settings:
    display: Reading
    backlight: Reading
    compensation: Temperature
    away: Temperature
    limits: Limits
    deadband: Temperature

    @property
    def scope(self) -> Literal["unresolved"]:
        return "unresolved"


@dataclass(frozen=True)
class Summary:
    """Raw bank position only; existence of a room depends separately on R21."""

    raw: int | None
    unit: Reading

    @property
    def quality(self) -> Quality:
        return _quality(self.raw)

    @property
    def powered(self) -> bool | None:
        return bool(self.raw & 1) if self.quality == "valid" else None

    @property
    def valve_open(self) -> bool | None:
        """Existing bit3 name, not newly qualified physical valve semantics."""
        return bool(self.raw & 8) if self.quality == "valid" else None

    @property
    def mode(self) -> Reading:
        if self.quality != "valid":
            return Reading(None, None, self.quality)
        return _choice((self.raw >> 1) & 3, _MODE)

    @property
    def current_code(self) -> int | None:
        return summary.decode_room(self.raw, 1).current_temperature if self.quality == "valid" else None

    @property
    def target_code(self) -> int | None:
        return summary.decode_room(self.raw, 1).target_temperature if self.quality == "valid" else None

    @property
    def current_temperature(self) -> float | None:
        if self.current_code is None or self.unit.value is None:
            return None
        return self.current_code * self.unit.value

    @property
    def target_temperature(self) -> float | None:
        if self.target_code is None or self.unit.value is None:
            return None
        return self.target_code * self.unit.value


@dataclass(frozen=True)
class RfObservation:
    state: Reading
    error: Reading


@dataclass(frozen=True)
class HvmObservation:
    """Immutable function result; no runtime registration, cache or I/O owner."""

    raw: tuple[int | None, ...]
    profile: Profile
    detail: Detail
    settings: Settings
    summaries: tuple[Summary, ...]
    rf: RfObservation
    boiler_raw: tuple[int | None, ...]  # R23/R24/R25/R60/R61/R62, no inferred support.
    unknown_raw: tuple[int | None, ...]  # R16/R17/R19/R63.

    @property
    def single_room_selected(self) -> bool:
        """Current raw guard: a valid one-room count with room 1 validly selected."""
        count, selected = self.profile.room_count, self.detail.selected_room
        return count.quality == "valid" and count.value == 1 and selected.quality == "valid" and selected.value == 1

    @property
    def climate_limits(self) -> tuple[int, int] | None:
        """Single-room presentation qualification; no mode, unit or firmware gate."""
        limits = self.settings.limits
        if self.single_room_selected and limits.status == "ordered":
            return limits.lower.value, limits.upper.value
        return None

    @property
    def selected_mode(self) -> str | None:
        """Known R2 mode only while the attributed selected-room summary agrees.

        R0 power is a separate axis; an OFF room keeps its stored mode.
        """
        selected, mode = self.detail.selected_room, self.detail.mode
        if selected.value is None or mode.value is None:
            return None
        return mode.value if self.summaries[selected.value - 1].mode.value == mode.value else None


def decode(registers: Sequence[int | None]) -> HvmObservation:
    """Observe one explicit input, retaining incomplete/invalid data without defaults."""
    raw = tuple(registers)

    def word(index: int) -> int | None:
        return raw[index] if index < len(raw) else None

    profile = Profile(
        _choice(word(20), {0: "district", 1: "boiler"}), _bounded(word(21), 1, 7),
        _choice(word(22), {0: "MODBUS", 1: "TTA485", 2: "CVNET", 3: "SEZ9x_KI", 4: "SEZ9x_DS"}),
        _choice(word(26), {0: "SiHAS", 1: "SEZ91", 2: "SEZ92", 3: "SEZ NO LCD"}),
        _reading(word(27)), _choice(word(59), {0: 1.0, 1: 0.5}),
    )
    selected = _bounded(word(10), 1, profile.room_count.value or 0)
    detail = Detail(selected, _flag(word(0)), _temperature(word(1)), _choice(word(2), _MODE), _temperature(word(3)),
                    _flag(word(4)), _flag(word(5)), _reading(word(9)))
    settings = Settings(_choice(word(6), _DISPLAY), _choice(word(7), _BACKLIGHT), _temperature(word(8), offset=50),
                        _temperature(word(11)), Limits(_reading(word(12)), _reading(word(13))), _temperature(word(14)))
    return HvmObservation(raw, profile, detail, settings, tuple(Summary(word(index), profile.summary_unit) for index in range(52, 59)),
                          RfObservation(_reading(word(15)), _flag(word(18))), tuple(word(index) for index in (23, 24, 25, 60, 61, 62)),
                          tuple(word(index) for index in (16, 17, 19, 63)))


class HvmSummaryState(tuple):
    """Room-summary tuple plus the observation decoded from the same snapshot.

    A `tuple` subclass so existing room indexing/length consumers compose
    transparently. The strict observation, its single-room climate-limit
    qualification, the provisional-control context and the stored schedule
    slots/banks are decoded once here, so HA projections never decode raw
    registers a second time. `controls_qualified` combines the runtime's
    prepared control eligibility with this snapshot's single-room guard; HA
    projection and the control selectors both read this one result.
    """

    def __new__(cls, rooms: Sequence[summary.RoomState], observation: HvmObservation, controls_qualified: bool,
                schedule_slots: tuple[schedule.DefaultSlot, ...] = (), periodic_banks: tuple[schedule.PeriodicRepeat, ...] = ()):
        self = super().__new__(cls, rooms)
        self.observation = observation
        self.climate_limits = observation.climate_limits
        self.controls_qualified = controls_qualified
        self.schedule_slots = schedule_slots
        self.periodic_banks = periodic_banks
        return self


@dataclass(frozen=True)
class Prepared:
    """One runtime's firmware choices; the text and components remain export metadata.

    `controls_eligible` is the static provisional-control support decision; the
    current single-room guard is decided separately from each snapshot.
    """

    firmware: str | None
    version: tuple[int, int] | None
    schedule_layout: schedule.Layout | None
    controls_eligible: bool


def prepare(firmware: str | None) -> Prepared:
    """Parse the configured firmware once: exact control eligibility and the schedule layout."""
    version = firmware_version(firmware)
    return Prepared(firmware, version, schedule.schedule_format(version), version == CONTROL_FIRMWARE)


def decode_summary(registers: Sequence[int], prepared: Prepared) -> HvmSummaryState:
    """Compose the legacy room summary with this module's observation of the same registers."""
    observed = decode(registers)
    return HvmSummaryState(summary.decode(registers), observed, prepared.controls_eligible and observed.single_room_selected,
                           schedule.decode_slots(registers, prepared.schedule_layout),
                           schedule.decode_periodic_banks(registers, prepared.schedule_layout))


def _integer(value: int, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} requires an integer in {low}..{high}")
    return value


def selector_intent(room: int, room_count: int) -> tuple[int, int]:
    """Offline R10 data only; room is strictly 1-based, never an index."""
    _integer(room_count, 1, 7, "Room count")
    return 10, _integer(room, 1, room_count, "Selected room")


def power_intent(powered: bool) -> tuple[int, int]:
    if type(powered) is not bool:
        raise ValueError("Desired power requires bool")
    return 0, int(powered)


def target_intent(tenths: int) -> tuple[int, int]:
    """R1 app-static 0..99 Celsius guide, not R12/R13 or a physical limit."""
    return 1, _integer(tenths, 0, 990, "Detail target tenths")


def mode_intent(mode: int) -> tuple[int, int]:
    return 2, _integer(mode, 0, 2, "Detail mode")


def on_minutes_intent(minutes: int) -> tuple[int, int]:
    """Integer wire representation only; physical/app operating range unresolved."""
    return 9, _integer(minutes, 0, 65535, "ON minutes")


def display_intent(mode: int) -> tuple[int, int]:
    return 6, _integer(mode, 0, 3, "Display code")


def backlight_intent(mode: int) -> tuple[int, int]:
    return 7, _integer(mode, 0, 3, "Backlight code")


def compensation_intent(tenths: int) -> tuple[int, int]:
    """Offset encoding only; no physical temperature guide is inferred."""
    return 8, _integer(tenths, -50, 65485, "Compensation tenths") + 50


def away_intent(tenths: int) -> tuple[int, int]:
    return 11, _integer(tenths, 0, 65535, "Away tenths")


def upper_limit_intent(celsius: int) -> tuple[int, int]:
    return 12, _integer(celsius, 0, 65535, "Upper integer Celsius")


def lower_limit_intent(celsius: int) -> tuple[int, int]:
    return 13, _integer(celsius, 0, 65535, "Lower integer Celsius")


def deadband_intent(tenths: int) -> tuple[int, int]:
    return 14, _integer(tenths, 0, 65535, "Deadband tenths")


def rs485_id_intent(value: int) -> tuple[int, int]:
    return 27, _integer(value, 0, 255, "RS-485 ID")
