"""Existing ACM register interpretation and single-command intent."""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from functools import partial

from .definition import CommandExecution, DeviceDefinition, Feature, register_writes

REG_ON_OFF = 0
REG_SET_POINT = 1
REG_MODE = 2
REG_FAN = 3
REG_SWING = 4
REG_EXEC_UCR = 5
REG_AC_TEMP = 6
REG_VIBRATION = 7
REG_LIST_UCR1 = 54
REG_LIST_UCR2 = 55
MODES = ("cool", "dry", "fan_only", "auto", "heat")
SWING_MODES = ("off", "vertical", "horizontal", "both")
FAN_MODES = ("low", "medium", "high", "auto")
REMOTE_BUTTONS = 20


@dataclass(frozen=True)
class AcmState:
    mode: str
    target_temperature: int
    current_temperature: float | None
    fan: str
    swing: str
    vibration: bool
    remote_buttons: tuple[int, ...]


def vibration(registers: Sequence[int]) -> bool:
    return registers[REG_VIBRATION] != 0


def remote_buttons(registers: Sequence[int]) -> tuple[int, ...]:
    mask = registers[REG_LIST_UCR1] + (registers[REG_LIST_UCR2] << 16)
    return tuple(index for index in range(REMOTE_BUTTONS) if mask & (1 << index))


def decode(registers: Sequence[int], config: int) -> AcmState:
    return AcmState(
        "off" if registers[REG_ON_OFF] == 0 else MODES[registers[REG_MODE]],
        registers[REG_SET_POINT], registers[REG_AC_TEMP] / 10 if config >= 1 else None,
        FAN_MODES[registers[REG_FAN]], SWING_MODES[registers[REG_SWING]],
        vibration(registers), remote_buttons(registers),
    )


def power_command(powered: bool) -> tuple[int, int]:
    return REG_ON_OFF, 1 if powered else 0


def mode_command(mode: str) -> tuple[int, int]:
    return REG_MODE, MODES.index(mode)


def _nearest_steps(temperature: float, step: float) -> int:
    """Whole `step` units nearest to `temperature`; an exact midpoint selects the higher temperature.

    Decimal arithmetic on the shortest float text keeps midpoint decisions independent of binary representation error.
    """
    units = Decimal(str(temperature)) / Decimal(str(step))
    return int((units + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def temperature_command(temperature: float) -> tuple[int, int]:
    return REG_SET_POINT, _nearest_steps(temperature, 1)


def fan_command(mode: str) -> tuple[int, int]:
    return REG_FAN, FAN_MODES.index(mode)


def swing_command(mode: str) -> tuple[int, int]:
    return REG_SWING, SWING_MODES.index(mode)


def remote_command(index: int) -> tuple[int, int]:
    return REG_EXEC_UCR, index


async def async_mode_transition(previous_mode: str | None, mode: str, execution: CommandExecution) -> None:
    """Preserve the verified ACM off/mode/power sequencing and its 0.5s settle wait."""
    if mode == "off":
        await execution.write(power_command(False))
        return
    if previous_mode != mode:
        await execution.write(mode_command(mode))
        await execution.wait(0.5)
    if previous_mode == "off":
        await execution.write(power_command(True))


async def _mode_policy(snapshot, mode: str, execution: CommandExecution) -> None:
    await async_mode_transition(snapshot.state.mode, mode, execution)


def definition(config: int) -> DeviceDefinition:
    """Mode sequencing from the transaction-start mode; every other command is one register write without refresh."""
    return DeviceDefinition(decode=partial(decode, config=config), features={
        "mode": Feature(read_supported=True, command=_mode_policy),
        "temperature": Feature(read_supported=True, command=register_writes(lambda snapshot, value: (temperature_command(value),))),
        "fan": Feature(read_supported=True, command=register_writes(lambda snapshot, value: (fan_command(value),))),
        "swing": Feature(read_supported=True, command=register_writes(lambda snapshot, value: (swing_command(value),))),
        **{f"remote_{index}": Feature(command=register_writes(lambda snapshot, value, index=index: (remote_command(index),)))
           for index in range(REMOTE_BUTTONS)},
    })
