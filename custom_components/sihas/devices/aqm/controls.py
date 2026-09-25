"""AQM device-backed setting controls: command selection and definition policies.

Each selector receives the command transaction's starting AQM state and returns
the ordered `(register, value)` intents, or raises ValueError before any I/O.
Every intent edits only its own register; R29 edits preserve the opposite byte
of the starting word. Refreshed readback is the only published result.

Public ranges and options are the SiHAS Home Assistant contract taken from the
retained manufacturer-app edit evidence, never the uint16 wire range and never
the R52 link-condition guidance. Settings without such an evidence-backed edit
contract (the PM2.5, PM10 and CO2 threshold triplets and LCD R23) have no writer.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from ..controls import NumberRange
from . import settings
from .metadata import is_word
from .state import AqmState

if TYPE_CHECKING:
    from ..definition import CommandExecution, CommandPolicy, CommandValue
    from ..state import DeviceSnapshot

Intents = tuple[tuple[int, int], ...]

# App TVOC threshold edit: integer ppb with 0 <= low < mid < high <= 9999; each submission is validated as a whole triplet.
TVOC_THRESHOLD_MINIMUM, TVOC_THRESHOLD_MAXIMUM = 0, 9999
TVOC_THRESHOLDS = ("tvoc_low_threshold", "tvoc_mid_threshold", "tvoc_high_threshold")
_TVOC_LOW_REGISTER = 19
_BACKLIGHT_REGISTER, _PRIMARY_REGISTER, _COMPENSATION_REGISTER = 22, 24, 29

TEMPERATURE_COMPENSATION_RANGE = NumberRange(-49, 50, 1)  # App-guided -4.9..5.0 C step 0.1.
HUMIDITY_COMPENSATION_RANGE = NumberRange(-99, 100, 1)  # App-guided -9.9..10.0 %RH step 0.1.

BACKLIGHT_OPTIONS: Mapping[str, settings.BacklightMode] = MappingProxyType({
    "always_off": settings.BacklightMode.ALWAYS_OFF, "always_on": settings.BacklightMode.ALWAYS_ON,
    "auto_off": settings.BacklightMode.AUTO_OFF, "illuminance": settings.BacklightMode.ILLUMINANCE,
})
LCD_PRIMARY_OPTIONS: Mapping[str, settings.LcdPrimary] = MappingProxyType({
    "pm25": settings.LcdPrimary.PM25, "pm10": settings.LcdPrimary.PM10, "co2": settings.LcdPrimary.CO2,
    "tvoc": settings.LcdPrimary.TVOC, "illuminance": settings.LcdPrimary.ILLUMINANCE, "time": settings.LcdPrimary.TIME,
    "cycle": settings.LcdPrimary.CYCLE,
})


def _settings(state: AqmState) -> settings.AqmSettings:
    if not isinstance(state, AqmState) or state.settings is None:
        raise ValueError("No AQM settings readback is published")
    return state.settings


def tvoc_threshold_range(state: AqmState, position: int) -> NumberRange | None:
    """Values for one TVOC word that keep the whole triplet inside the app contract.

    The other two words come from the readback. A missing/invalid counterpart, or
    counterparts that already violate the contract, yield None: no range is
    fabricated and no write is allowed.
    """
    if type(position) is not int or not 0 <= position <= 2:
        raise ValueError(f"Unknown TVOC threshold position: {position}")
    triplet = _settings(state).tvoc
    words = (triplet.low, triplet.mid, triplet.high)
    fixed = [word for index, word in enumerate(words) if index != position]
    if not all(is_word(word) and TVOC_THRESHOLD_MINIMUM <= word <= TVOC_THRESHOLD_MAXIMUM for word in fixed):
        return None
    if position != 1 and not fixed[0] < fixed[1]:
        return None
    low = words[position - 1] + 1 if position > 0 else TVOC_THRESHOLD_MINIMUM
    high = words[position + 1] - 1 if position < 2 else TVOC_THRESHOLD_MAXIMUM
    return NumberRange(low * 10, high * 10, 10) if low <= high else None


def tvoc_threshold_intents(state: AqmState, value: int | float | Decimal, *, position: int) -> Intents:
    """One R19/R20/R21 word; the other two starting words are preserved exactly."""
    if (current := tvoc_threshold_range(state, position)) is None:
        raise ValueError("AQM TVOC thresholds have no valid current range")
    return ((_TVOC_LOW_REGISTER + position, current.tenths(value) // 10),)


def _compensation_word(state: AqmState) -> int:
    compensation = _settings(state).compensation
    if compensation.quality != "valid":
        raise ValueError("AQM R29 compensation word is not a preservable readback")
    return compensation.raw


def temperature_compensation_intents(state: AqmState, value: int | float | Decimal) -> Intents:
    """R29 low byte only; the starting humidity byte is preserved exactly."""
    tenths = TEMPERATURE_COMPENSATION_RANGE.tenths(value)
    return ((_COMPENSATION_REGISTER, settings.encode_temperature(_compensation_word(state), tenths)),)


def humidity_compensation_intents(state: AqmState, value: int | float | Decimal) -> Intents:
    """R29 high byte only; the starting temperature byte is preserved exactly."""
    tenths = HUMIDITY_COMPENSATION_RANGE.tenths(value)
    return ((_COMPENSATION_REGISTER, settings.encode_humidity(_compensation_word(state), tenths)),)


def _option(options: Mapping[str, Any], option: Any, name: str):
    if option not in options:
        raise ValueError(f"Unsupported AQM {name} option: {option}")
    return options[option]


def backlight_intents(state: AqmState, option: str) -> Intents:
    return ((_BACKLIGHT_REGISTER, settings.encode_backlight(_option(BACKLIGHT_OPTIONS, option, "backlight"))),)


def lcd_primary_intents(state: AqmState, option: str) -> Intents:
    """R24 on the LCD display interpretation only."""
    mode = _option(LCD_PRIMARY_OPTIONS, option, "LCD primary display")
    display = state.metadata.display if isinstance(state, AqmState) and state.metadata is not None else None
    return ((_PRIMARY_REGISTER, settings.encode_display_selection(mode, display=display, register=_PRIMARY_REGISTER)),)


def current_option(options: Mapping[str, Any], selection: settings.Selection) -> str | None:
    """Readback option name; unknown, missing or invalid codes have no option."""
    return next((name for name, mode in options.items() if mode is selection.mode), None)


def temperature_compensation(state: AqmState) -> float | None:
    compensation = _settings(state).compensation
    return compensation.temperature_tenths / 10 if compensation.quality == "valid" else None


def humidity_compensation(state: AqmState) -> float | None:
    compensation = _settings(state).compensation
    return compensation.humidity_tenths / 10 if compensation.quality == "valid" else None


def tvoc_threshold(state: AqmState, position: int) -> int | None:
    triplet = _settings(state).tvoc
    word = (triplet.low, triplet.mid, triplet.high)[position]
    return word if is_word(word) else None


def policy(select: Callable[[AqmState, Any], Intents]) -> CommandPolicy:
    """Definition policy: select from the starting snapshot, write in order, then refresh.

    A failed write stops the remaining intents; the refresh still publishes what the device holds.
    """
    async def execute(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
        if execution.refresh is None:
            raise ValueError("AQM controls require a readback refresh effect")
        for intent in select(cast(AqmState, snapshot.state), value):
            if not await execution.write(intent):
                break
        await execution.refresh()
    return execute


def commands(display: Literal["fnd", "lcd"] | None) -> Mapping[str, CommandPolicy]:
    """Setting command policies for one display interpretation; LCD R24 exists only for the LCD branch."""
    result: dict[str, CommandPolicy] = {
        **{key: policy(partial(tvoc_threshold_intents, position=position)) for position, key in enumerate(TVOC_THRESHOLDS)},
        "temperature_compensation": policy(temperature_compensation_intents),
        "humidity_compensation": policy(humidity_compensation_intents),
        "backlight": policy(backlight_intents),
    }
    if display == "lcd":
        result["lcd_primary_display"] = policy(lcd_primary_intents)
    return MappingProxyType(result)
