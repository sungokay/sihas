"""Provisional HVM single-register control commands.

Each selector receives the command transaction's starting publication and
returns exactly one `(register, value)` intent, or raises ValueError before
any I/O. Controls are limited to the qualified single-room context published
by `observation.decode_summary`; readback through the normal coordinator
refresh remains authoritative and no other register is written implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from . import observation, schedule

if TYPE_CHECKING:
    from ..state import DeviceSnapshot

# HA preset option -> R2 detail mode code; names follow the observed mode semantics.
PRESETS = {"temperature": 0, "time": 1, "away": 2}
# HA option -> R6 code. Raw 0 and 3 both read as `both`; selecting it writes the app canonical 3.
DISPLAY_OPTIONS = {"both": 3, "current": 1, "target": 2}
# HA option -> R7 code, matching the observation's backlight names.
BACKLIGHT_OPTIONS = {"auto_off": 0, "on_off": 1, "always_off": 2, "always_on": 3}


@dataclass(frozen=True)
class NumberRange:
    """Home Assistant public capability range in exact tenths of the presented unit.

    This is SiHAS user-facing policy. It is neither the device's storable wire
    range (uint16 values far beyond these bounds are accepted) nor the small set
    of points used for physical write qualification.
    """

    low: int
    high: int
    step: int

    @property
    def minimum(self) -> Decimal:
        return Decimal(self.low) / 10

    @property
    def maximum(self) -> Decimal:
        return Decimal(self.high) / 10

    @property
    def increment(self) -> Decimal:
        return Decimal(self.step) / 10

    def tenths(self, value: int | float | Decimal) -> int:
        """Exact on-step tenths inside the range, otherwise ValueError."""
        tenths = observation.exact_tenths(value)
        if not self.low <= tenths <= self.high or (tenths - self.low) % self.step:
            raise ValueError(f"Value {value} is outside {self.minimum}..{self.maximum} step {self.increment}")
        return tenths


COMPENSATION_RANGE = NumberRange(0, 30, 5)  # 0.0..3.0 C step 0.5
ON_MINUTES_RANGE = NumberRange(100, 500, 100)  # 10..50 minutes step 10
AWAY_RANGE = NumberRange(50, 1000, 1)  # 5.0..100.0 C step 0.1
DEADBAND_RANGE = NumberRange(1, 100, 1)  # 0.1..10.0 C step 0.1
# Integer-Celsius policy bounds shared by R13 lower and R12 upper; each endpoint is further bounded by its counterpart.
LIMIT_MINIMUM, LIMIT_MAXIMUM = 0, 100


def _limit_counterpart(endpoint: observation.Reading) -> int | None:
    return endpoint.value if endpoint.quality == "valid" and endpoint.value is not None else None


def lower_limit_range(observed: observation.HvmObservation) -> NumberRange | None:
    """R13 range from the published R12 readback: 0 .. upper - 1 C, never above the policy's highest ordered lower.

    A missing/invalid counterpart or an empty range yields None: no range is fabricated and no write is allowed.
    """
    upper = _limit_counterpart(observed.settings.limits.upper)
    if upper is None:
        return None
    high = min(upper - 1, LIMIT_MAXIMUM - 1)
    return NumberRange(LIMIT_MINIMUM * 10, high * 10, 10) if high >= LIMIT_MINIMUM else None


def upper_limit_range(observed: observation.HvmObservation) -> NumberRange | None:
    """R12 range from the published R13 readback: lower + 1 .. 100 C, never below the policy's lowest ordered upper."""
    lower = _limit_counterpart(observed.settings.limits.lower)
    if lower is None:
        return None
    low = max(lower + 1, LIMIT_MINIMUM + 1)
    return NumberRange(low * 10, LIMIT_MAXIMUM * 10, 10) if low <= LIMIT_MAXIMUM else None


def _qualified_state(snapshot: DeviceSnapshot | None) -> observation.HvmSummaryState:
    state = snapshot.state if snapshot is not None else None
    if not isinstance(state, observation.HvmSummaryState) or not state.controls_qualified:
        raise ValueError("HVM control is outside the qualified single-room context")
    return state


def _qualified(snapshot: DeviceSnapshot | None) -> observation.HvmObservation:
    return _qualified_state(snapshot).observation


def preset_command(snapshot: DeviceSnapshot | None, preset: str) -> tuple[int, int]:
    """R2 only; power, schedule and settings registers are never written with it."""
    _qualified(snapshot)
    return observation.mode_intent(_option(PRESETS, preset, "preset"))


def _option(options: dict[str, int], option: str, name: str) -> int:
    if option not in options:
        raise ValueError(f"Unsupported HVM {name} option: {option}")
    return options[option]


def display_command(snapshot: DeviceSnapshot | None, option: str) -> tuple[int, int]:
    """R6 only."""
    _qualified(snapshot)
    return observation.display_intent(_option(DISPLAY_OPTIONS, option, "display"))


def backlight_command(snapshot: DeviceSnapshot | None, option: str) -> tuple[int, int]:
    """R7 only; no auto-off timeout is inferred."""
    _qualified(snapshot)
    return observation.backlight_intent(_option(BACKLIGHT_OPTIONS, option, "backlight"))


def compensation_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> tuple[int, int]:
    """R8 only: tenths plus the +50 offset."""
    _qualified(snapshot)
    return observation.compensation_intent(COMPENSATION_RANGE.tenths(value))


def on_minutes_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> tuple[int, int]:
    """R9 only: integer minutes without schedule scaling; R2 time mode is not written."""
    _qualified(snapshot)
    return observation.on_minutes_intent(ON_MINUTES_RANGE.tenths(value) // 10)


def away_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> tuple[int, int]:
    """R11 only: tenths."""
    _qualified(snapshot)
    return observation.away_intent(AWAY_RANGE.tenths(value))


def deadband_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> tuple[int, int]:
    """R14 only: tenths."""
    _qualified(snapshot)
    return observation.deadband_intent(DEADBAND_RANGE.tenths(value))


def _limit_range(capability: NumberRange | None, name: str) -> NumberRange:
    if capability is None:
        raise ValueError(f"HVM {name} limit has no valid counterpart readback")
    return capability


def lower_limit_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> tuple[int, int]:
    """R13 only; the range from the starting R12 keeps the pair strictly ordered. R12 and the target are never written."""
    capability = _limit_range(lower_limit_range(_qualified(snapshot)), "lower")
    return observation.lower_limit_intent(capability.tenths(value) // 10)


def upper_limit_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> tuple[int, int]:
    """R12 only; the range from the starting R13 keeps the pair strictly ordered. R13 and the target are never written."""
    capability = _limit_range(upper_limit_range(_qualified(snapshot)), "upper")
    return observation.upper_limit_intent(capability.tenths(value) // 10)


def general_slot_command(snapshot: DeviceSnapshot | None, slot: int, enabled: bool) -> tuple[int, int]:
    """Only the slot's B-word enable bit, from the starting publication's decoded B word.

    A slot that did not decode (missing/invalid word or unsupported firmware)
    cannot be preserved and is rejected; the manufacturer app owns every other field.
    """
    slots = _qualified_state(snapshot).schedule_slots
    if type(slot) is not int or not 0 <= slot < len(slots) or slots[slot].time is None:
        raise ValueError(f"HVM general schedule slot is not a preservable readback: {slot}")
    return schedule.slot_enable_intent(slot, slots[slot].raw[1], enabled)


def periodic_bank_command(snapshot: DeviceSnapshot | None, bank: int, enabled: bool) -> tuple[int, int]:
    """Only the bank's A-word enable bit, from the starting publication's decoded A word.

    An undecodable bank cannot be preserved and is rejected; the manufacturer
    app owns every other periodic field.
    """
    banks = _qualified_state(snapshot).periodic_banks
    if type(bank) is not int or not 0 <= bank < len(banks) or banks[bank].fields is None:
        raise ValueError(f"HVM periodic schedule bank is not a preservable readback: {bank}")
    return schedule.periodic_enable_intent(bank, banks[bank].raw[0], enabled)
