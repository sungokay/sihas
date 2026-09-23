"""Verified BCM read semantics; no operation-mode or heating-level writes."""
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from decimal import Decimal, ROUND_FLOOR
import math
from typing import Literal

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
OCCUPANCY_HOME = "home"
OCCUPANCY_AWAY = "away"
WATER_UNKNOWN = "unknown"
_WATER_STATES = {0: "normal", 1: "needs_refill"}
_HOT_WATER_LEVELS = {1: ("low", "high"), 2: ("low", "medium", "high")}
Registers = Sequence[int | None]
Quality = Literal["valid", "missing", "invalid", "reversed", "unknown"]


class BcmController(Enum):
    NR_5S_FR_5 = "NR-5S/FR-5"
    NR_10E = "NR-10E"


_CONTROLLERS = {(0, 5): BcmController.NR_5S_FR_5, (0, 10): BcmController.NR_10E}


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
    controller = _CONTROLLERS.get((maker, model))
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
class BcmLimits:
    hot_water: BcmRange
    room: BcmRange
    ondol: BcmRange
    # R21's range-policy hint does not interpret the current R3 value or qualify a writer.
    hot_water_kind: Literal["level", "temperature"] | None


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


def decode_limits(registers: Registers) -> BcmLimits:
    """Read mutable bounds without applying them to the existing command/HA policy."""
    known = identify(registers).controller is not None
    upper = _word(registers, 21)
    kind: Literal["level", "temperature"] | None = None
    if known and upper is not None:
        if upper in (1, 2):
            kind = "level"
        elif upper >= 10:
            kind = "temperature"
    hot_water = _range(_raw(registers, 22), _raw(registers, 21), known)
    if hot_water.quality == "valid" and kind is None:
        hot_water = BcmRange(hot_water.lower_raw, hot_water.upper_raw, "unknown")
    return BcmLimits(hot_water, _range(_raw(registers, 24), _raw(registers, 23), known),
                     _range(_raw(registers, 26), _raw(registers, 25), known), kind)


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


def decode_timer_validation(registers: Registers) -> BcmTimerValidation:
    """Do not extend the two known controllers' validation semantics to another maker."""
    raw = _raw(registers, 28)
    quality: Quality
    if raw is None:
        quality = "missing"
    elif not _is_word(raw):
        quality = "invalid"
    elif identify(registers).controller is None:
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
    """App-static representation; physical evidence is bounded to the two-level range."""
    bounds = limits.hot_water
    quality = "missing" if raw is None else "invalid" if not _is_word(raw) else bounds.quality
    if quality != "valid":
        return BcmHotWaterSetting(raw, None, None, quality)
    if not bounds.minimum <= raw <= bounds.maximum:
        return BcmHotWaterSetting(raw, None, None, "invalid")
    if raw <= 9:
        labels = _HOT_WATER_LEVELS.get(bounds.maximum)
        if labels is None or limits.hot_water_kind != "level":
            return BcmHotWaterSetting(raw, None, None, "unknown")
        return BcmHotWaterSetting(raw, "level", labels[raw], "valid",
                                  two_level_read and bounds.minimum == 0 and bounds.maximum == 1)
    if limits.hot_water_kind != "temperature" or bounds.minimum < 10:
        return BcmHotWaterSetting(raw, None, None, "unknown")
    return BcmHotWaterSetting(raw, "temperature", raw, "valid")


def encode_hot_water(value: str | int, setting: BcmHotWaterSetting, limits: BcmLimits) -> int:
    """Pure candidate codec, never command qualification or a write intent."""
    current = decode_hot_water(setting.raw, limits)
    if setting.quality != "valid" or current.quality != "valid" or current.kind != setting.kind:
        raise ValueError("Hot-water representation is unknown or inconsistent")
    if current.kind == "level":
        labels = _HOT_WATER_LEVELS[limits.hot_water.maximum]
        if value not in labels:
            raise ValueError("Unknown hot-water level")
        raw = labels.index(value)
    else:
        if type(value) is not int:
            raise ValueError("Hot-water temperature requires an integer")
        raw = value
    if not limits.hot_water.minimum <= raw <= limits.hot_water.maximum:
        raise ValueError("Hot-water value is outside current bounds")
    return raw


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
    visible = limits.hot_water.maximum > 9 and raw != 0
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
    # Only this reported setting has physical read evidence. Broader candidates remain static.
    qualified = observed_read and quality == "valid" and raw == 110 and validation.raw == 1205
    return BcmTimerSetting(raw, period, minutes, allowed, quality, qualified)


def encode_timer(period_hours: int, run_minutes: int, validation: BcmTimerValidation) -> int:
    """Encode evidenced normal periods only; no zero/half-hour controller assumption."""
    if type(period_hours) is not int or period_hours <= 0 or validation.allows(period_hours, run_minutes) is not True:
        raise ValueError("Timer input is unknown, invalid or outside the normal codec")
    return period_hours * 100 + run_minutes


class BcmHeatMode(Enum):
    Room = 0
    Ondol = 1


@dataclass(frozen=True)
class BcmOpMode:
    isOnsuOn: bool
    isHeatOn: bool
    heatMode: BcmHeatMode


@dataclass(frozen=True)
class BcmOperation:
    """Full R4 observation; active selection is separate from the legacy bit2 selector."""

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

    @property
    def compatibility(self) -> BcmOpMode | None:
        if self.quality != "valid":
            return None
        return BcmOpMode(self.hot_water, self.heating, BcmHeatMode.Ondol if self.ondol else BcmHeatMode.Room)

    @property
    def active_selection(self) -> BcmHeatMode | None:
        return self.compatibility.heatMode if self.heating else None


def decode_operation(raw: int | None) -> BcmOperation:
    return BcmOperation(raw, "missing" if raw is None else "valid" if _is_word(raw) else "invalid")


_OPERATION_BITS = {"hot_water": 1, "heating": 2, "ondol": 4, "bath": 8}


def edit_operation(original: int, **changes: bool) -> int:
    """Offline edit of explicit original raw bits; no physical high-bit policy implied."""
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


def decode_heating_level(raw: int | None, identity: BcmIdentity) -> BcmHeatingLevel:
    quality: Quality = "missing" if raw is None else "invalid" if not _is_word(raw) else "unknown"
    if quality == "unknown" and identity.controller in (BcmController.NR_5S_FR_5, BcmController.NR_10E) and identity.quality == "valid":
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


@dataclass(frozen=True)
class BcmState:
    operation: BcmOpMode | None
    mode: str | None
    action: str | None
    current_temperature: int | None
    target_temperature: int | None
    manufacturer: BoilerManufactuer | int | None
    powered: bool | None
    away: bool | None
    scheduled: bool | None
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


def parse_oper_mode(registers: Registers) -> BcmOpMode | None:
    return decode_operation(_raw(registers, REG_OPERMODE)).compatibility


def operating_mode(registers: Registers) -> str | None:
    power, schedule, away = (_word(registers, index) for index in (REG_ONOFF, REG_TIMERMODE, REG_OUTMODE))
    if power is None:
        return None
    if power == 0:
        return "off"
    if schedule is None:
        return None
    if schedule == 1:
        return "schedule"
    if away is None:
        return None
    if away == 1:
        return "away"
    return "temperature"


def heating_action(registers: Registers) -> str | None:
    power, firing = _word(registers, REG_ONOFF), _word(registers, REG_FIRE_STATE)
    if power is None:
        return None
    if power == 0:
        return "off"
    if firing is None:
        return None
    return "idle" if firing == 0 else "heating"


def occupancy(registers: Registers) -> str | None:
    value = _word(registers, REG_OUTMODE)
    return None if value is None else OCCUPANCY_AWAY if value == 1 else OCCUPANCY_HOME


def schedule_enabled(registers: Registers) -> bool | None:
    value = _word(registers, REG_TIMERMODE)
    return None if value is None else value == 1


def problem(registers: Registers) -> bool | None:
    value = _word(registers, REG_ERRORST)
    return None if value is None else value != 0


def connected(registers: Registers) -> bool | None:
    value = _word(registers, REG_ONLINEST)
    return None if value is None else value == 0


def water_status(registers: Registers) -> str | None:
    value = _word(registers, REG_WATERST)
    return None if value is None else _WATER_STATES.get(value, WATER_UNKNOWN)


def decode(registers: Registers, *, two_level_read: bool = False, timer_read: bool = False) -> BcmState:
    operation_flags = decode_operation(_raw(registers, REG_OPERMODE))
    operation = operation_flags.compatibility
    current = target = None
    if operation is not None:
        if operation.heatMode == BcmHeatMode.Room:
            raw_current = _word(registers, REG_ROOMTEMP)
            current = math.floor(raw_current / 10) if raw_current is not None else None
            target = _word(registers, REG_ROOMSETPT)
        else:
            current, target = _word(registers, REG_ONDOLTEMP), _word(registers, REG_ONDOLSETPT)
    identity = identify(registers)
    maker = identity.manufacturer_raw
    manufacturer = BoilerManufactuer(maker) if maker is not None and _is_word(maker) and maker in BoilerManufactuer else maker
    power, away = _word(registers, REG_ONOFF), _word(registers, REG_OUTMODE)
    limits, timer_validation = decode_limits(registers), decode_timer_validation(registers)
    return BcmState(
        operation, operating_mode(registers), heating_action(registers), current, target, manufacturer,
        None if power is None else power == 1, None if away is None else away == 1,
        schedule_enabled(registers), problem(registers), connected(registers), water_status(registers),
        identity, limits, timer_validation,
        decode_hot_water(_raw(registers, REG_HOT_WATER), limits, two_level_read=two_level_read),
        decode_timer(_raw(registers, REG_TIMER), timer_validation, observed_read=timer_read),
        decode_hot_water_temperature(_raw(registers, REG_HOT_WATER_TEMP), limits),
        operation_flags, decode_heating_level(_raw(registers, 29), identity), decode_settings(registers),
    )


def power_command(powered: bool) -> tuple[int, int]:
    return REG_ONOFF, 1 if powered else 0


def occupancy_command(option: str) -> tuple[int, int]:
    return REG_OUTMODE, 1 if option == OCCUPANCY_AWAY else 0


def schedule_command(enabled: bool) -> tuple[int, int]:
    return REG_TIMERMODE, 1 if enabled else 0


def _nearest_steps(temperature: float, step: float) -> int:
    """Whole `step` units nearest to `temperature`; an exact midpoint selects the higher temperature.

    Decimal arithmetic on the shortest float text keeps midpoint decisions independent of binary representation error.
    """
    units = Decimal(str(temperature)) / Decimal(str(step))
    return int((units + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def temperature_command(heat_mode: BcmHeatMode, temperature: float) -> tuple[int, int]:
    return (REG_ROOMSETPT if heat_mode == BcmHeatMode.Room else REG_ONDOLSETPT), _nearest_steps(temperature, 1)
