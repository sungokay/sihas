"""BCM control selection and definition command policies.

Each selector receives the command transaction's starting BCM state and returns
the complete ordered `(register, value)` intents, or raises ValueError before
any I/O. Only the explicit power control writes R0; preset, program, target,
setting and toggle intents never change power. Raw-preserving controls edit
only their owned bit of the starting word.

The validated NR-5S/FR-5 definition attaches these policies; other controller
definitions do not inherit them. Refreshed readback is the only published
result, and every writer here is provisional until physical write/readback
qualification.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, ROUND_FLOOR
from typing import TYPE_CHECKING, Any, cast

from .. import controls
from ..controls import NumberRange
from . import schedule, settings
from . import state as bcm

if TYPE_CHECKING:
    from ..definition import CommandExecution, CommandPolicy, CommandValue
    from ..state import DeviceSnapshot

Intents = tuple[tuple[int, int], ...]

HEATING_LEVELS = ("low", "medium", "high")
BACKLIGHT_OPTIONS = {"auto_off": settings.Backlight.AUTO_OFF, "on_off": settings.Backlight.ON_OFF,
                     "always_off": settings.Backlight.ALWAYS_OFF, "always_on": settings.Backlight.ALWAYS_ON}
TOUCH_LOCK_OPTIONS = {"unlocked": settings.TouchLock.UNLOCKED, "temperature": settings.TouchLock.TEMPERATURE,
                      "full": settings.TouchLock.FULL}
COMPENSATION_RANGE = NumberRange(-50, 50, 1)  # App-guided -5.0..5.0 C step 0.1.
# Program -> the register it asserts; normal asserts neither.
_PROGRAM_REGISTERS = {"normal": None, "away": bcm.REG_OUTMODE, "timer": bcm.REG_TIMERMODE}


def _option(options, option: Any, name: str):
    if option not in options:
        raise ValueError(f"Unsupported BCM {name} option: {option}")
    return options[option] if isinstance(options, dict) else options.index(option)


def power_intents(state: bcm.BcmState, powered: bool) -> Intents:
    """R0 only; preset, program, targets and configuration are never rewritten with it."""
    if type(powered) is not bool:
        raise ValueError(f"Invalid BCM power request: {powered}")
    return ((bcm.REG_ONOFF, int(powered)),)


def preset_intents(state: bcm.BcmState, preset: str) -> Intents:
    """R4 raw-preserving edit: bath, the inactive selector for hot_water_only and every unknown bit survive."""
    _option(bcm.PRESETS, preset, "preset")
    operation = state.operation_flags
    if operation.quality != "valid":
        raise ValueError("BCM R4 operation word is not a preservable readback")
    if preset == "hot_water_only":
        edited = bcm.edit_operation(operation.raw, hot_water=True, heating=False)
    else:
        edited = bcm.edit_operation(operation.raw, hot_water=True, heating=True, ondol=preset == "ondol")
    return ((bcm.REG_OPERMODE, edited),)


def program_intents(state: bcm.BcmState, program: str) -> Intents:
    """Smallest R5/R6 writes converging to the requested tuple, clearing the conflicting register first.

    A contradictory starting tuple is converged as well. R0, R4 and R7 are never written.
    """
    wanted = _option(_PROGRAM_REGISTERS, program, "program")
    words = dict(zip((bcm.REG_OUTMODE, bcm.REG_TIMERMODE), state.program_raw))
    if not all(type(word) is int and 0 <= word <= 65535 for word in words.values()):
        raise ValueError("BCM R5/R6 program words are not a preservable readback")
    intents = [(register, 0) for register, word in words.items() if register != wanted and word != 0]
    if wanted is not None and words[wanted] != 1:
        intents.append((wanted, 1))
    return tuple(intents)


def _nearest_steps(temperature: float, step: float) -> int:
    """Whole `step` units nearest to `temperature`; an exact midpoint selects the higher temperature.

    Decimal arithmetic on the shortest float text keeps midpoint decisions independent of binary representation error.
    """
    units = Decimal(str(temperature)) / Decimal(str(step))
    return int((units + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def temperature_intents(state: bcm.BcmState, temperature: float) -> Intents:
    """Climate target: only the register selected by the published projection, rounded to 1 C."""
    target = state.target
    if target is None:
        raise ValueError("BCM has no target-temperature control in the current operation")
    if type(temperature) not in (int, float) or isinstance(temperature, bool):
        raise ValueError(f"Invalid BCM temperature: {temperature}")
    value = _nearest_steps(temperature, 1)
    bounds = target.bounds  # A validated target always carries its usable range; other profiles carry none.
    if bounds is not None and not bounds.minimum <= value <= bounds.maximum:
        raise ValueError(f"BCM target {value} is outside {bounds.minimum}..{bounds.maximum}")
    return ((target.register, value),)


def target_range(bounds: bcm.BcmRange) -> NumberRange | None:
    """Direct target range from the current device-reported bounds, step 1 C; no range is fabricated.

    Uses the same `state.target_bounds` rule as the climate target projection.
    """
    if (usable := bcm.target_bounds(bounds)) is None:
        return None
    return NumberRange(usable.minimum * 10, usable.maximum * 10, 10)


def room_target_range(state: bcm.BcmState) -> NumberRange | None:
    return target_range(state.limits.room)


def ondol_target_range(state: bcm.BcmState) -> NumberRange | None:
    return target_range(state.limits.ondol)


def _counterpart(raw: int | None, bounds: bcm.BcmRange) -> int | None:
    # A reversed pair still has a usable counterpart word; missing/invalid/unknown ranges do not.
    return raw if bounds.quality in ("valid", "reversed") else None


def room_lower_limit_range(state: bcm.BcmState) -> NumberRange | None:
    return controls.lower_limit_range(_counterpart(state.limits.room.upper_raw, state.limits.room))


def room_upper_limit_range(state: bcm.BcmState) -> NumberRange | None:
    return controls.upper_limit_range(_counterpart(state.limits.room.lower_raw, state.limits.room))


def ondol_lower_limit_range(state: bcm.BcmState) -> NumberRange | None:
    return controls.lower_limit_range(_counterpart(state.limits.ondol.upper_raw, state.limits.ondol))


def ondol_upper_limit_range(state: bcm.BcmState) -> NumberRange | None:
    return controls.upper_limit_range(_counterpart(state.limits.ondol.lower_raw, state.limits.ondol))


def _number(register: int, capability: Callable[[bcm.BcmState], NumberRange | None], name: str):
    def select(state: bcm.BcmState, value: int | float | Decimal) -> Intents:
        if (current := capability(state)) is None:
            raise ValueError(f"BCM {name} has no valid current range")
        return ((register, current.tenths(value) // 10),)
    return select


room_target_intents = _number(bcm.REG_ROOMSETPT, room_target_range, "room target")
ondol_target_intents = _number(bcm.REG_ONDOLSETPT, ondol_target_range, "ondol target")
room_upper_limit_intents = _number(23, room_upper_limit_range, "room upper limit")
room_lower_limit_intents = _number(24, room_lower_limit_range, "room lower limit")
ondol_upper_limit_intents = _number(25, ondol_upper_limit_range, "ondol upper limit")
ondol_lower_limit_intents = _number(26, ondol_lower_limit_range, "ondol lower limit")


def compensation_intents(state: bcm.BcmState, value: int | float | Decimal) -> Intents:
    """R18 only: raw = tenths + 50. The room temperature word is not compensated again."""
    return ((18, settings.encode_compensation(COMPENSATION_RANGE.tenths(value))),)


def heating_level_intents(state: bcm.BcmState, level: str) -> Intents:
    return ((bcm.REG_HEATING_LEVEL, _option(HEATING_LEVELS, level, "heating level")),)


def backlight_intents(state: bcm.BcmState, option: str) -> Intents:
    return ((17, settings.encode_backlight(_option(BACKLIGHT_OPTIONS, option, "backlight"))),)


def touch_lock_intents(state: bcm.BcmState, option: str) -> Intents:
    return ((52, settings.encode_touch_lock(_option(TOUCH_LOCK_OPTIONS, option, "touch lock"))),)


def buzzer_intents(state: bcm.BcmState, enabled: bool) -> Intents:
    if type(enabled) is not bool:
        raise ValueError(f"Invalid BCM buzzer request: {enabled}")
    return ((62, settings.encode_buzzer(settings.Buzzer.ENABLED if enabled else settings.Buzzer.DISABLED)),)


def general_toggle(state: bcm.BcmState, slot: int) -> controls.StoredToggle | None:
    if type(slot) is not int or not 0 <= slot < len(state.schedule_slots):
        raise ValueError(f"Unknown BCM general schedule slot: {slot}")
    return schedule.slot_toggle(slot, state.schedule_slots[slot])


def interval_toggle(state: bcm.BcmState) -> controls.StoredToggle | None:
    return schedule.interval_toggle(state.interval)


def _toggle_intents(toggle: controls.StoredToggle | None, enabled: bool, name: str) -> Intents:
    if toggle is None:
        raise ValueError(f"BCM {name} is not a preservable readback")
    return (toggle.intent(enabled),)


def general_slot_intents(state: bcm.BcmState, enabled: bool, *, slot: int) -> Intents:
    """Only the slot's B-word bit15 from the starting raw pair; empty storage is never enabled."""
    return _toggle_intents(general_toggle(state, slot), enabled, f"general schedule slot {slot}")


def interval_intents(state: bcm.BcmState, enabled: bool) -> Intents:
    """Only R50 bit0 from the starting raw word; the rest of R50 and all of R51 are preserved."""
    return _toggle_intents(interval_toggle(state), enabled, "interval repeat")


def current_option(options: dict, mode) -> str | None:
    """Readback option name for a decoded setting enum; unknown codes have no option."""
    return next((name for name, value in options.items() if value is mode), None)


def program_attributes(state: bcm.BcmState) -> dict[str, Any]:
    """Persistent R7 simple-timer detail when it decodes inside the read-qualified envelope."""
    timer = state.timer
    if not timer.read_qualified:
        return {}
    return {"timer_period_hours": timer.period_hours, "timer_run_minutes": timer.run_minutes}


def general_slot_attributes(state: bcm.BcmState, slot: int) -> dict[str, Any]:
    """Decoded, meaningful slot fields only; undecodable fields are omitted."""
    item = state.schedule_slots[slot]
    time = item.time
    if time is None:
        return {}
    result: dict[str, Any] = {"kind": time.kind}
    if time.kind == "date":
        result.update(month=time.month, day=time.day)
    else:
        result["weekdays"] = list(controls.weekday_names(time.weekdays))
    result.update(repeat=time.repeat, hour=time.hour, minute=time.minute)
    setting = item.setting
    if isinstance(setting, schedule.NewSetting):
        result.update(mode=setting.mode, preserve_value=setting.preserve_value)
        if setting.preserve_value or setting.mode in ("bath", "away"):
            return result
        if setting.mode in ("room", "ondol"):
            result["temperature"] = setting.parameter
        elif setting.mode == "timer":
            result["timer_period_hours"], result["timer_run_minutes"] = schedule.decode_timer_parameter(setting.parameter)
        elif (level := schedule.decode_hot_water_level(setting.parameter, state.limits.hot_water)) is not None:
            result["hot_water_level"] = level
    return result


def interval_attributes(state: bcm.BcmState) -> dict[str, Any]:
    fields = state.interval.fields
    if fields is None:
        return {}
    return {"weekdays": list(controls.weekday_names(fields.weekdays)), "start_hour": fields.start_hour,
            "end_hour": fields.end_hour, "period_hours": fields.period_hours, "run_minutes": fields.run_minutes,
            "temperature_control": fields.temperature_control}


def policy(select: Callable[[bcm.BcmState, Any], Intents]) -> CommandPolicy:
    """Definition policy: select from the starting snapshot, write in order, then refresh.

    A failed write stops the remaining intents so no partial transition is extended;
    the refresh still publishes whatever the device actually holds, then the failure propagates.
    """
    async def execute(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
        if execution.refresh is None:
            raise ValueError("BCM controls require a readback refresh effect")
        for intent in select(cast(bcm.BcmState, snapshot.state), value):
            try:
                await execution.write(intent)
            except Exception:
                await execution.refresh()
                raise
        await execution.refresh()
    return execute
