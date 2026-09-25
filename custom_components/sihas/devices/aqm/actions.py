"""AQM one-shot intents and policies; read values never supply action payloads."""
from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from ..definition import CommandExecution, CommandValue

if TYPE_CHECKING:
    from ..state import DeviceSnapshot


def tvoc_calibration() -> tuple[int, int]:
    return (5, 1)


def co2_calibration() -> tuple[int, int]:
    return (26, 1)


def log_reset(day: int) -> tuple[int, int]:
    """Sunday=0 through Saturday=6; today=7 is a distinct device action."""
    if type(day) is not int or not 0 <= day <= 7:
        raise ValueError("Log reset requires an integer day action in 0..7")
    return (8, day)


ACTION_INTENTS = MappingProxyType({
    "tvoc_calibration": tvoc_calibration(),
    "co2_calibration": co2_calibration(),
    "log_reset_sunday": log_reset(0),
    "log_reset_monday": log_reset(1),
    "log_reset_tuesday": log_reset(2),
    "log_reset_wednesday": log_reset(3),
    "log_reset_thursday": log_reset(4),
    "log_reset_friday": log_reset(5),
    "log_reset_saturday": log_reset(6),
    "log_reset_today": log_reset(7),
})


async def execute(action: str, snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
    """Invoke an attached action once, without replay, retry or fake readback."""
    if value is not True:
        raise ValueError("AQM actions require the True invocation token")
    if action not in ACTION_INTENTS:
        raise ValueError(f"Unknown AQM action: {action}")
    if execution.write_once is None:
        raise ValueError("Single-attempt execution is unavailable")
    await execution.write_once(ACTION_INTENTS[action])
