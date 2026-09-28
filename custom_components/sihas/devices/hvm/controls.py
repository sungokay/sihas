"""HVM extension selectors and manufacturer command-list policies.

Each selector receives the command transaction's starting publication and
returns ordered `(index, value)` pairs, or raises ValueError before
any I/O. Controls are limited to the qualified single-room context published
by `observation.decode_summary`; readback through the normal coordinator
refresh remains authoritative. Schedule toggles include their unchanged companion
word in the same command list; room power/target retain their separate packed-summary command owner.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING

from ..definition import CommandExecution, CommandPolicy, CommandValue
from ..controls import NumberRange, lower_limit_range as lower_range, upper_limit_range as upper_range
from . import observation, schedule

if TYPE_CHECKING:
    from ..state import DeviceSnapshot

Intents = tuple[tuple[int, int], ...]

# HA preset option -> R2 detail mode code; names follow the observed mode semantics.
PRESETS = {"temperature": 0, "time": 1, "away": 2}
# HA option -> R6 code. Raw 0 and 3 both read as `both`; selecting it writes the app canonical 3.
DISPLAY_OPTIONS = {"both": 3, "current": 1, "target": 2}
# HA option -> R7 code, matching the observation's backlight names.
BACKLIGHT_OPTIONS = {"auto_off": 0, "on_off": 1, "always_off": 2, "always_on": 3}


COMPENSATION_RANGE = NumberRange(0, 30, 5)  # 0.0..3.0 C step 0.5
ON_MINUTES_RANGE = NumberRange(100, 500, 100)  # 10..50 minutes step 10
AWAY_RANGE = NumberRange(50, 1000, 1)  # 5.0..100.0 C step 0.1
DEADBAND_RANGE = NumberRange(1, 100, 1)  # 0.1..10.0 C step 0.1


def _limit_counterpart(endpoint: observation.Reading) -> int | None:
    return endpoint.value if endpoint.quality == "valid" and endpoint.value is not None else None


def lower_limit_range(observed: observation.HvmObservation) -> NumberRange | None:
    """R13 range from the published R12 readback, under the shared ordered-limit policy."""
    return lower_range(_limit_counterpart(observed.settings.limits.upper))


def upper_limit_range(observed: observation.HvmObservation) -> NumberRange | None:
    """R12 range from the published R13 readback, under the shared ordered-limit policy."""
    return upper_range(_limit_counterpart(observed.settings.limits.lower))


def _qualified_state(snapshot: DeviceSnapshot | None) -> observation.HvmSummaryState:
    state = snapshot.state if snapshot is not None else None
    if not isinstance(state, observation.HvmSummaryState) or not state.controls_qualified:
        raise ValueError("HVM control is outside the qualified single-room context")
    return state


def _qualified(snapshot: DeviceSnapshot | None) -> observation.HvmObservation:
    return _qualified_state(snapshot).observation


def preset_command(snapshot: DeviceSnapshot | None, preset: str) -> Intents:
    """R2 only; power, schedule and settings registers are never written with it."""
    _qualified(snapshot)
    return (observation.mode_intent(_option(PRESETS, preset, "preset")),)


def _option(options: dict[str, int], option: str, name: str) -> int:
    if option not in options:
        raise ValueError(f"Unsupported HVM {name} option: {option}")
    return options[option]


def display_command(snapshot: DeviceSnapshot | None, option: str) -> Intents:
    """R6 only."""
    _qualified(snapshot)
    return (observation.display_intent(_option(DISPLAY_OPTIONS, option, "display")),)


def backlight_command(snapshot: DeviceSnapshot | None, option: str) -> Intents:
    """R7 only; no auto-off timeout is inferred."""
    _qualified(snapshot)
    return (observation.backlight_intent(_option(BACKLIGHT_OPTIONS, option, "backlight")),)


def compensation_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> Intents:
    """R8 only: tenths plus the +50 offset."""
    _qualified(snapshot)
    return (observation.compensation_intent(COMPENSATION_RANGE.tenths(value)),)


def on_minutes_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> Intents:
    """R9 only: integer minutes without schedule scaling; R2 time mode is not written."""
    _qualified(snapshot)
    return (observation.on_minutes_intent(ON_MINUTES_RANGE.tenths(value) // 10),)


def away_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> Intents:
    """R11 only: tenths."""
    _qualified(snapshot)
    return (observation.away_intent(AWAY_RANGE.tenths(value)),)


def deadband_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> Intents:
    """R14 only: tenths."""
    _qualified(snapshot)
    return (observation.deadband_intent(DEADBAND_RANGE.tenths(value)),)


def _limit_range(capability: NumberRange | None, name: str) -> NumberRange:
    if capability is None:
        raise ValueError(f"HVM {name} limit has no valid counterpart readback")
    return capability


def lower_limit_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> Intents:
    """R13 only; the range from the starting R12 keeps the pair strictly ordered. R12 and the target are never written."""
    capability = _limit_range(lower_limit_range(_qualified(snapshot)), "lower")
    return (observation.lower_limit_intent(capability.tenths(value) // 10),)


def upper_limit_command(snapshot: DeviceSnapshot | None, value: int | float | Decimal) -> Intents:
    """R12 only; the range from the starting R13 keeps the pair strictly ordered. R13 and the target are never written."""
    capability = _limit_range(upper_limit_range(_qualified(snapshot)), "upper")
    return (observation.upper_limit_intent(capability.tenths(value) // 10),)


def general_slot_command(snapshot: DeviceSnapshot | None, slot: int, enabled: bool) -> Intents:
    """One A/B command list changing only the slot's B-word enable bit.

    A valid pair is sufficient; semantic slot decoding is optional attribute metadata.
    Missing/invalid words and enabling empty storage are rejected; the manufacturer
    app owns every other field.
    """
    slots = _qualified_state(snapshot).schedule_slots
    if type(slot) is not int or not 0 <= slot < len(slots) or (toggle := schedule.slot_toggle(slot, slots[slot])) is None:
        raise ValueError(f"HVM general schedule slot is not a preservable readback: {slot}")
    intent = toggle.intent(enabled)
    return ((intent[0] - 1, slots[slot].raw[0]), intent)


def periodic_bank_command(snapshot: DeviceSnapshot | None, bank: int, enabled: bool) -> Intents:
    """One A/B command list changing only the bank's A-word enable bit.

    A valid pair is sufficient; semantic periodic decoding is optional attribute
    metadata. The manufacturer app owns every other periodic field.
    """
    banks = _qualified_state(snapshot).periodic_banks
    if type(bank) is not int or not 0 <= bank < len(banks) or (toggle := schedule.periodic_toggle(bank, banks[bank])) is None:
        raise ValueError(f"HVM periodic schedule bank is not a preservable readback: {bank}")
    intent = toggle.intent(enabled)
    return (intent, (intent[0] + 1, banks[bank].raw[1]))


def policy(
    select: Callable[[DeviceSnapshot, CommandValue], Intents],
    reading: Callable[[observation.HvmObservation], CommandValue | None] | None = None,
) -> CommandPolicy:
    """Reconcile decoded settings, or exact preserved schedule pairs, after one successful command list."""
    async def execute(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
        if execution.multi_control is None or execution.reconcile is None:
            raise ValueError("HVM controls require manufacturer command-list and readback reconciliation effects")
        intents = select(snapshot, value)

        def complete(current: DeviceSnapshot) -> bool:
            state = current.state
            if not isinstance(state, observation.HvmSummaryState) or not state.controls_qualified:
                return False
            if reading is not None:
                return reading(state.observation) == value
            return all(current.registers[index] == expected for index, expected in intents)

        await execution.multi_control(intents)
        await execution.reconcile(complete)
    return execute
