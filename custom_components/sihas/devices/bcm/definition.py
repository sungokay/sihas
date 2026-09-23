"""BCM family-owned controller resolution with unchanged compatibility commands."""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast

from . import state as bcm
from ..definition import CommandExecution, CommandValue, DeviceDefinition, Feature

if TYPE_CHECKING:
    from ..state import DeviceSnapshot


async def mode(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
    """Preserve the verified decisions from the transaction's starting snapshot."""
    state = cast(bcm.BcmState, snapshot.state)
    if value in ("temperature", "schedule"):
        if not state.powered:
            await execution.write(bcm.power_command(True))
            await execution.wait(1)
        if state.away:
            await execution.write(bcm.occupancy_command("home"))
            await execution.wait(1)
        if value == "schedule":
            await execution.write(bcm.schedule_command(True))
        elif state.scheduled:
            await execution.write(bcm.schedule_command(False))
    elif value == "away":
        if not state.powered:
            await execution.write(bcm.power_command(True))
            await execution.wait(1)
        await execution.write(bcm.occupancy_command("away"))
    elif value == "off" and state.powered:
        await execution.write(bcm.power_command(False))


async def temperature(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
    state = cast(bcm.BcmState, snapshot.state)
    await execution.write(bcm.temperature_command(state.operation.heatMode, cast(float, value)))


async def occupancy(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
    await execution.write(bcm.occupancy_command(cast(str, value)))


async def schedule(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
    await execution.write(bcm.schedule_command(cast(bool, value)))


COMPATIBILITY = DeviceDefinition(
    decode=bcm.decode,
    features={
        "mode": Feature(read_supported=True, command=mode),
        "temperature": Feature(read_supported=True, command=temperature),
        "occupancy": Feature(read_supported=True, command=occupancy),
        "schedule": Feature(read_supported=True, command=schedule),
        "problem": Feature(read_supported=True),
        "connectivity": Feature(read_supported=True),
        "water_status": Feature(read_supported=True),
        "controller_identity": Feature(read_supported=True),
    },
)

_KNOWN_FEATURES = {**COMPATIBILITY.features, "limits": Feature(read_supported=True), "timer_validation": Feature(read_supported=True)}

# User-supplied physical read evidence is recorded in docs/bcm-read-qualification.md.
# Decoded mutable state further restricts applicability; no new command is attached.
NR_5S_FR_5 = DeviceDefinition(
    decode=partial(bcm.decode, two_level_read=True, timer_read=True),
    features={**_KNOWN_FEATURES, "hot_water_level": Feature(read_supported=True), "timer_setting": Feature(read_supported=True)},
)
NR_10E = DeviceDefinition(decode=bcm.decode, features=_KNOWN_FEATURES)

_MODEL_DEFINITIONS = {bcm.BcmController.NR_5S_FR_5: NR_5S_FR_5, bcm.BcmController.NR_10E: NR_10E}


def resolve(registers: bcm.Registers) -> DeviceDefinition:
    """Match the evidenced manufacturer/model pair, never a nearest controller.

    Unmatched input retains raw identity and the existing compatibility behavior;
    it receives no known-model range semantics or additional write qualification.
    """
    return _MODEL_DEFINITIONS.get(bcm.identify(registers).controller, COMPATIBILITY)


def decode(registers: bcm.Registers) -> bcm.BcmState:
    """Keep the existing standalone family decoder entry point on this authority."""
    return cast(bcm.BcmState, resolve(registers).decode(registers))
