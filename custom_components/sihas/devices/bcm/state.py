"""BCM register semantics and the validated climate/program projection; no I/O or write execution."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from enum import Enum, IntEnum
import math
import re
from typing import Literal

from . import schedule
from .settings import BcmSettings
from .settings import decode_settings

REG_ONOFF = 0
REG_ROOMSETPT = 1
REG_ONDOLSETPT = 2
REG_HOT_WATER = 3
REG_OPERMODE = 4
REG_OUTMODE = 5
REG_TIMERMODE = 6
REG_TIMER = 7
REG_ROOMTEMP = 8
REG_ONDOLTEMP = 9
REG_HOT_WATER_TEMP = 10
REG_FIRE_STATE = 11
REG_ERRORST = 12
REG_WATERST = 13
REG_ONLINEST = 14
REG_MANUFACTURER = 15
REG_MODEL = 16
REG_HEATING_LEVEL = 29
WATER_UNKNOWN = "unknown"
_WATER_STATES = {0: "normal", 1: "needs_refill"}
_HOT_WATER_LEVELS = {1: ("low", "high"), 2: ("low", "medium", "high")}
Registers = Sequence[int | None]
Quality = Literal["valid", "missing", "invalid", "reversed", "unknown"]
Preset = Literal["room", "ondol", "hot_water_only"]
Program = Literal["normal", "away", "timer"]
PRESETS: tuple[Preset, ...] = ("room", "ondol", "hot_water_only")
PROGRAMS: tuple[Program, ...] = ("normal", "away", "timer")
# Observed NR-5S/FR-5 R28 validation state for the physically read R7 envelope.
_OBSERVED_TIMER_VALIDATION = 1205


class BcmController(Enum):
    NR_5S_FR_5 = "NR-5S/FR-5"
    NR_10E = "NR-10E"


# Evidenced (R15, R16) identities; composition selects each controller's semantics from this registration.
CONTROLLERS = {(0, 5): BcmController.NR_5S_FR_5, (0, 10): BcmController.NR_10E}


def _raw(registers: Registers, index: int) -> int | None:
    return registers[index] if index < len(registers) else None


def _is_word(value: int | None) -> bool:
    return type(value) is int and 0 <= value <= 65535


def _word(registers: Registers, index: int) -> int | None:
    value = _raw(registers, index)
    return value if _is_word(value) else None


@dataclass(frozen=True)
class BcmIdentity:
    manufacturer_raw: int | None
    model_raw: int | None
    controller: BcmController | None
    quality: Quality

    @property
    def evidence(self) -> str:
        return "app_static" if self.controller is not None else "unknown"


def identify(registers: Registers) -> BcmIdentity:
    """Interpret only evidenced composite identities, retaining unmatched raw values."""
    maker, model = _raw(registers, REG_MANUFACTURER), _raw(registers, REG_MODEL)
    if maker is None or model is None:
        return BcmIdentity(maker, model, None, "missing")
    if not _is_word(maker) or not _is_word(model):
        return BcmIdentity(maker, model, None, "invalid")
    controller = CONTROLLERS.get((maker, model))
    return BcmIdentity(maker, model, controller, "valid" if controller is not None else "unknown")


@dataclass(frozen=True)
class BcmRange:
    """Reported bounds; valid means consistent app encoding, not hardware qualification."""

    lower_raw: int | None
    upper_raw: int | None
    quality: Quality

    @property
    def minimum(self) -> int | None:
        return self.lower_raw if self.quality == "valid" else None

    @property
    def maximum(self) -> int | None:
        return self.upper_raw if self.quality == "valid" else None


@dataclass(frozen=True)
class BcmHotWaterRange:
    """R22/R21 hot-water representation selected by R21; valid means consistent app encoding, not qualification.

    Level mode (R21=1/2) is defined by R21 alone: R22 is retained raw evidence with no
    established meaning there, so it is neither a lower bound nor a reason to reject the
    levels. Temperature mode (R21>=10) is the ordered R22..R21 range.
    """

    lower_raw: int | None
    upper_raw: int | None
    kind: Literal["level", "temperature"] | None
    quality: Quality

    @property
    def minimum(self) -> int | None:
        return self.lower_raw if self.quality == "valid" and self.kind == "temperature" else None

    @property
    def maximum(self) -> int | None:
        return self.upper_raw if self.quality == "valid" and self.kind == "temperature" else None

    @property
    def levels(self) -> tuple[str, ...] | None:
        return _HOT_WATER_LEVELS[self.upper_raw] if self.quality == "valid" and self.kind == "level" else None


@dataclass(frozen=True)
class BcmLimits:
    hot_water: BcmHotWaterRange
    room: BcmRange
    ondol: BcmRange

    @property
    def hot_water_kind(self) -> Literal["level", "temperature"] | None:
        # R21's representation hint does not interpret the current R3 value or qualify a writer.
        return self.hot_water.kind


def _range(lower: int | None, upper: int | None, known: bool) -> BcmRange:
    quality: Quality
    if lower is None or upper is None:
        quality = "missing"
    elif not _is_word(lower) or not _is_word(upper):
        quality = "invalid"
    elif not known:
        quality = "unknown"
    elif lower > upper:
        quality = "reversed"
    else:
        quality = "valid"
    return BcmRange(lower, upper, quality)


def decode_limits(registers: Registers, *, known_encoding: bool) -> BcmLimits:
    """Read current mutable bounds; each consumer decides whether its profile applies them.

    `known_encoding` is the composed controller semantics, not a model lookup:
    without it every range keeps its raw words with unknown quality.
    """
    upper = _word(registers, 21)
    kind: Literal["level", "temperature"] | None = None
    if known_encoding and upper is not None:
        if upper in _HOT_WATER_LEVELS:
            kind = "level"
        elif upper >= 10:
            kind = "temperature"
    words = _range(_raw(registers, 22), _raw(registers, 21), known_encoding)
    quality = words.quality
    if kind == "level" and quality == "reversed":
        quality = "valid"  # R22 is not ordered against the level count.
    elif kind is None and quality == "valid":
        quality = "unknown"
    return BcmLimits(BcmHotWaterRange(words.lower_raw, words.upper_raw, kind, quality),
                     _range(_raw(registers, 24), _raw(registers, 23), known_encoding),
                     _range(_raw(registers, 26), _raw(registers, 25), known_encoding))


@dataclass(frozen=True)
class BcmTimerValidation:
    """R28 app input validation only; no R7 encoding or physical write qualification."""

    raw: int | None
    quality: Quality

    @property
    def period_upper_hours(self) -> float | None:
        return self.raw / 100 if self.quality == "valid" and self.raw is not None else None

    @property
    def run_minute_step(self) -> int | None:
        # Zero means the app imposes no divisibility condition, not zero allowed minutes.
        return self.raw % 100 if self.quality == "valid" and self.raw is not None else None

    def allows(self, period_hours: float, run_minutes: int) -> bool | None:
        """Return unknown for unqualified metadata; True only means app-input acceptance."""
        upper, step = self.period_upper_hours, self.run_minute_step
        if upper is None or step is None:
            return None
        if type(period_hours) not in (int, float) or not math.isfinite(period_hours) or type(run_minutes) is not int:
            return False
        if not 0 <= period_hours <= min(24, upper) or not 1 <= run_minutes <= 60:
            return False
        if period_hours != 0.5 and period_hours % 1 != 0:
            return False
        if period_hours == 0.5 and run_minutes >= 30 or period_hours == 1 and run_minutes == 60:
            return False
        return step == 0 or run_minutes % step == 0


def decode_timer_validation(registers: Registers, *, known_encoding: bool) -> BcmTimerValidation:
    """R28 validation under the composed controller encoding; never extended to an unmatched controller."""
    raw = _raw(registers, 28)
    quality: Quality
    if raw is None:
        quality = "missing"
    elif not _is_word(raw):
        quality = "invalid"
    elif not known_encoding:
        quality = "unknown"
    else:
        quality = "valid"
    return BcmTimerValidation(raw, quality)


@dataclass(frozen=True)
class BcmHotWaterSetting:
    raw: int | None
    kind: Literal["level", "temperature"] | None
    value: str | int | None
    quality: Quality
    read_qualified: bool = False


def decode_hot_water(raw: int | None, limits: BcmLimits, *, two_level_read: bool = False) -> BcmHotWaterSetting:
    """App-static representation; physical evidence is bounded to the two-level representation."""
    bounds = limits.hot_water
    quality = "missing" if raw is None else "invalid" if not _is_word(raw) else bounds.quality
    if quality != "valid":
        return BcmHotWaterSetting(raw, None, None, quality)
    if (levels := bounds.levels) is not None:
        if raw >= len(levels):
            return BcmHotWaterSetting(raw, None, None, "invalid")
        return BcmHotWaterSetting(raw, "level", levels[raw], "valid", two_level_read and len(levels) == 2)
    if bounds.kind != "temperature":
        return BcmHotWaterSetting(raw, None, None, "unknown")
    if not bounds.minimum <= raw <= bounds.maximum:
        return BcmHotWaterSetting(raw, None, None, "invalid")
    if raw <= 9 or bounds.minimum < 10:
        return BcmHotWaterSetting(raw, None, None, "unknown")
    return BcmHotWaterSetting(raw, "temperature", raw, "valid")


def encode_hot_water(value: str | int, setting: BcmHotWaterSetting, limits: BcmLimits) -> int:
    """Pure candidate codec, never command qualification or a write intent."""
    current = decode_hot_water(setting.raw, limits)
    if setting.quality != "valid" or current.quality != "valid" or current.kind != setting.kind:
        raise ValueError("Hot-water representation is unknown or inconsistent")
    if (levels := limits.hot_water.levels) is not None:
        if value not in levels:
            raise ValueError("Unknown hot-water level")
        return levels.index(value)
    if type(value) is not int:
        raise ValueError("Hot-water temperature requires an integer")
    if not limits.hot_water.minimum <= value <= limits.hot_water.maximum:
        raise ValueError("Hot-water value is outside current bounds")
    return value


@dataclass(frozen=True)
class BcmHotWaterTemperature:
    raw: int | None
    temperature: int | None
    visible: bool | None
    quality: Quality


def decode_hot_water_temperature(raw: int | None, limits: BcmLimits) -> BcmHotWaterTemperature:
    """App presentation only; neither visibility nor a numeric value proves a sensor."""
    quality = "missing" if raw is None else "invalid" if not _is_word(raw) else limits.hot_water.quality
    if quality != "valid":
        return BcmHotWaterTemperature(raw, None, None, quality)
    # The app shows R10 only for the temperature representation (R21 > 9) and a non-zero value.
    visible = limits.hot_water.kind == "temperature" and raw != 0
    return BcmHotWaterTemperature(raw, raw if visible else None, visible, "valid")


@dataclass(frozen=True)
class BcmTimerSetting:
    raw: int | None
    period_hours: int | None
    run_minutes: int | None
    app_valid: bool | None
    quality: Quality
    read_qualified: bool = False


def decode_timer(raw: int | None, validation: BcmTimerValidation, *, observed_read: bool = False) -> BcmTimerSetting:
    """Normal app codec with raw<100 ambiguity retained, independent of write support."""
    if raw is None or not _is_word(raw):
        return BcmTimerSetting(raw, None, None, None, "missing" if raw is None else "invalid")
    period, minutes = divmod(raw, 100)
    allowed = validation.allows(period, minutes)
    quality = validation.quality if allowed is None else "valid" if allowed else "invalid"
    if raw < 100 and quality == "valid":
        quality = "unknown"
    # Physical read evidence covers the normal codec under the observed R28 validation state.
    qualified = observed_read and quality == "valid" and validation.raw == _OBSERVED_TIMER_VALIDATION
    return BcmTimerSetting(raw, period, minutes, allowed, quality, qualified)


def encode_timer(period_hours: int, run_minutes: int, validation: BcmTimerValidation) -> int:
    """Encode evidenced normal periods only; no zero/half-hour controller assumption."""
    if type(period_hours) is not int or period_hours <= 0 or validation.allows(period_hours, run_minutes) is not True:
        raise ValueError("Timer input is unknown, invalid or outside the normal codec")
    return period_hours * 100 + run_minutes


@dataclass(frozen=True)
class BcmOperation:
    """Full R4 observation: hot-water/heating/ondol/bath flags plus retained unknown high bits."""

    raw: int | None
    quality: Quality

    def _flag(self, mask: int) -> bool | None:
        return bool(self.raw & mask) if self.quality == "valid" else None

    @property
    def hot_water(self) -> bool | None:
        return self._flag(1)

    @property
    def heating(self) -> bool | None:
        return self._flag(2)

    @property
    def ondol(self) -> bool | None:
        return self._flag(4)

    @property
    def bath(self) -> bool | None:
        return self._flag(8)

    @property
    def unknown_bits(self) -> int | None:
        return self.raw & 0xFFF0 if self.quality == "valid" else None


def decode_operation(raw: int | None) -> BcmOperation:
    return BcmOperation(raw, "missing" if raw is None else "valid" if _is_word(raw) else "invalid")


_OPERATION_BITS = {"hot_water": 1, "heating": 2, "ondol": 4, "bath": 8}


def edit_operation(original: int, **changes: bool) -> int:
    """Edit named flags of an explicit original word, preserving every unspecified bit."""
    if not _is_word(original):
        raise ValueError("Operation requires an explicit uint16 original word")
    result = original
    for name, enabled in changes.items():
        if name not in _OPERATION_BITS or type(enabled) is not bool:
            raise ValueError("Operation edits require named bool flags")
        mask = _OPERATION_BITS[name]
        result = result | mask if enabled else result & ~mask
    return result


def encode_operation(*, hot_water: bool, heating: bool, ondol: bool, bath: bool) -> int:
    """App-static canonical low nibble from four explicit flags; never a write intent."""
    return edit_operation(0, hot_water=hot_water, heating=heating, ondol=ondol, bath=bath)


@dataclass(frozen=True)
class BcmHeatingLevel:
    raw: int | None
    value: Literal["low", "medium", "high"] | None
    quality: Quality


def decode_heating_level(raw: int | None, *, known_encoding: bool) -> BcmHeatingLevel:
    """R29 low/medium/high only under the composed controller encoding."""
    quality: Quality = "missing" if raw is None else "invalid" if not _is_word(raw) else "unknown"
    if quality == "unknown" and known_encoding:
        if raw in (0, 1, 2):
            return BcmHeatingLevel(raw, ("low", "medium", "high")[raw], "valid")
    return BcmHeatingLevel(raw, None, quality)


class BoilerManufactuer(IntEnum):
    KYUNGDONG = 0
    KITURAMI = 1
    DAESUNG = 2
    RINNAI = 3
    DMAX = 4
    RESERVED1 = 5
    RESERVED2 = 6


def decode_preset(operation: BcmOperation) -> Preset | None:
    """NR-5S/FR-5 climate preset from R4; any other flag combination has no guessed preset."""
    if operation.quality != "valid" or not operation.hot_water:
        return None
    if not operation.heating:
        return "hot_water_only"
    return "ondol" if operation.ondol else "room"


def decode_program(away: int | None, timer: int | None) -> Program | None:
    """R5 away / R6 simple-timer tuple; contradictory, unknown or missing words have no program."""
    return {(0, 0): "normal", (1, 0): "away", (0, 1): "timer"}.get((away, timer))


def decode_power(raw: int | None) -> bool | None:
    return {0: False, 1: True}.get(raw) if _is_word(raw) else None


def decode_burner(raw: int | None) -> bool | None:
    """Generic burner/flame activity; it does not prove space heating."""
    return raw != 0 if _is_word(raw) else None


def hvac_action(powered: bool | None, burner: bool | None) -> Literal["off", "idle"] | None:
    """Power OFF is off and an idle burner is idle; generic burner activity claims no heating action."""
    if powered is False:
        return "off"
    return "idle" if powered and burner is False else None


@dataclass(frozen=True)
class BcmTarget:
    """Stored target register selected for the climate projection.

    `bounds` is the device-reported dynamic range used by the validated profile;
    None means no device-reported range is applied to this projection.
    """

    register: int
    temperature: int | None
    bounds: BcmRange | None


def target_bounds(bounds: BcmRange) -> BcmRange | None:
    """The device-reported target range only when it is usable; the single rule for climate and direct target numbers."""
    return bounds if bounds.quality == "valid" else None


def climate_target(registers: Registers, operation: BcmOperation, preset: Preset | None, limits: BcmLimits,
                   *, validated: bool) -> BcmTarget | None:
    """Validated profile: the active preset selects R1 or R2 when its current range is usable.

    hot_water_only, no preset and an unusable range have no target control; no range is fabricated.
    Other profiles retain the R4 bit2 target selector without a device-reported range.
    """
    if validated:
        selected = {"room": (REG_ROOMSETPT, limits.room), "ondol": (REG_ONDOLSETPT, limits.ondol)}.get(preset)
        if selected is None or (bounds := target_bounds(selected[1])) is None:
            return None
        return BcmTarget(selected[0], _word(registers, selected[0]), bounds)
    if operation.quality != "valid":
        return None
    register = REG_ONDOLSETPT if operation.ondol else REG_ROOMSETPT
    return BcmTarget(register, _word(registers, register), None)


def _room_temperature(registers: Registers) -> float | None:
    raw = _word(registers, REG_ROOMTEMP)
    return raw / 10 if raw is not None else None


def current_temperature(registers: Registers, operation: BcmOperation, preset: Preset | None, *, validated: bool) -> float | int | None:
    """R8 room temperature in tenths or R9 ondol temperature.

    Validated profile: room and hot_water_only use R8 (the preserved bit2 of hot_water_only is not an active
    selection), ondol uses R9 and no preset has no current temperature. Other profiles retain the R4 bit2 selector.
    """
    if validated:
        if preset == "ondol":
            return _word(registers, REG_ONDOLTEMP)
        return _room_temperature(registers) if preset in ("room", "hot_water_only") else None
    if operation.quality != "valid":
        return None
    return _word(registers, REG_ONDOLTEMP) if operation.ondol else _room_temperature(registers)


def firmware_version(firmware: str | None) -> tuple[int, int] | None:
    """Dotted numeric components of the configured firmware text, or None."""
    match = re.fullmatch(r"V?([0-9]{1,2})\.([0-9]{1,3})", firmware) if isinstance(firmware, str) else None
    return (int(match[1]), int(match[2])) if match else None


@dataclass(frozen=True)
class BcmState:
    powered: bool | None
    preset: Preset | None
    program: Program | None
    program_raw: tuple[int | None, int | None]
    burner: bool | None
    action: Literal["off", "idle"] | None
    current_temperature: float | int | None
    target: BcmTarget | None
    room_target: int | None
    ondol_target: int | None
    manufacturer: BoilerManufactuer | int | None
    problem: bool | None
    connected: bool | None
    water_status: str | None
    identity: BcmIdentity
    limits: BcmLimits
    timer_validation: BcmTimerValidation
    hot_water: BcmHotWaterSetting
    timer: BcmTimerSetting
    hot_water_temperature: BcmHotWaterTemperature
    operation_flags: BcmOperation
    heating_level: BcmHeatingLevel
    settings: BcmSettings
    schedule_slots: tuple[schedule.ScheduleSlot, ...]
    interval: schedule.IntervalRepeat


def problem(registers: Registers) -> bool | None:
    value = _word(registers, REG_ERRORST)
    return None if value is None else value != 0


def connected(registers: Registers) -> bool | None:
    value = _word(registers, REG_ONLINEST)
    return None if value is None else value == 0


def water_status(registers: Registers) -> str | None:
    value = _word(registers, REG_WATERST)
    return None if value is None else _WATER_STATES.get(value, WATER_UNKNOWN)


SlotReader = Callable[[Registers], tuple[schedule.ScheduleSlot, ...]]


def decode(registers: Registers, *, known_encoding: bool = False, validated: bool = False,
           slots: SlotReader = partial(schedule.decode_slots, layout=None)) -> BcmState:
    """Decode one snapshot with the semantics its definition composed.

    `known_encoding` applies the app-static controller encoding of R21-R26 ranges,
    R28 timer validation and R29 levels. `validated` additionally applies the
    physically read NR-5S/FR-5 climate/program projection and read envelopes.
    `slots` is the prepared schedule reader. Identity is always reported from
    the current R15/R16 words, independently of these choices.
    """
    operation = decode_operation(_raw(registers, REG_OPERMODE))
    identity = identify(registers)
    maker = identity.manufacturer_raw
    manufacturer = BoilerManufactuer(maker) if maker is not None and _is_word(maker) and maker in BoilerManufactuer else maker
    limits = decode_limits(registers, known_encoding=known_encoding)
    timer_validation = decode_timer_validation(registers, known_encoding=known_encoding)
    powered, burner = decode_power(_raw(registers, REG_ONOFF)), decode_burner(_raw(registers, REG_FIRE_STATE))
    preset = decode_preset(operation) if validated else None
    program_raw = (_raw(registers, REG_OUTMODE), _raw(registers, REG_TIMERMODE))
    program = decode_program(*(value if _is_word(value) else None for value in program_raw)) if validated else None
    return BcmState(
        powered, preset, program, program_raw, burner, hvac_action(powered, burner),
        current_temperature(registers, operation, preset, validated=validated),
        climate_target(registers, operation, preset, limits, validated=validated),
        _word(registers, REG_ROOMSETPT), _word(registers, REG_ONDOLSETPT), manufacturer,
        problem(registers), connected(registers), water_status(registers),
        identity, limits, timer_validation,
        decode_hot_water(_raw(registers, REG_HOT_WATER), limits, two_level_read=validated),
        decode_timer(_raw(registers, REG_TIMER), timer_validation, observed_read=validated),
        decode_hot_water_temperature(_raw(registers, REG_HOT_WATER_TEMP), limits),
        operation, decode_heating_level(_raw(registers, REG_HEATING_LEVEL), known_encoding=known_encoding), decode_settings(registers),
        slots(registers), schedule.decode_interval(_raw(registers, 50), _raw(registers, 51)),
    )
