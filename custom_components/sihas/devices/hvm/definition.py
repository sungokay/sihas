"""HVM setup preparation and extension command-capability composition."""
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from ..definition import DeviceDefinition, Feature, register_writes
from . import controls, observation, schedule, summary

# Extension controls require this major version at or above the minimum minor version.
_CONTROL_FIRMWARE_MAJOR = 3
_CONTROL_FIRMWARE_MIN_MINOR = 33
# Packed-summary room power/target for every HVM runtime: one register write, then one readback refresh.
# Room words addressable inside the 64-register poll; the live room count selects which rooms exist.
ROOM_SLOTS = 64 - summary.HVM_STATE_START
_ROOM_FEATURES = {
    **{f"room_{room}_power": Feature(command=register_writes(partial(summary.room_power_intents, room=room), refresh=True))
       for room in range(ROOM_SLOTS)},
    **{f"room_{room}_target": Feature(command=register_writes(partial(summary.room_target_intents, room=room), refresh=True))
       for room in range(ROOM_SLOTS)},
}
_FEATURES = {
    "preset": Feature(read_supported=True, command=controls.policy(
        controls.preset_command, lambda o: o.selected_mode)),
    "display": Feature(read_supported=True, command=controls.policy(
        controls.display_command, lambda o: o.settings.display.value)),
    "backlight": Feature(read_supported=True, command=controls.policy(
        controls.backlight_command, lambda o: o.settings.backlight.value)),
    "temperature_compensation": Feature(read_supported=True, command=controls.policy(
        controls.compensation_command, lambda o: o.settings.compensation.tenths / 10 if o.settings.compensation.tenths is not None else None)),
    "on_minutes": Feature(read_supported=True, command=controls.policy(
        controls.on_minutes_command, lambda o: o.detail.on_minutes.value)),
    "away_temperature": Feature(read_supported=True, command=controls.policy(
        controls.away_command, lambda o: o.settings.away.tenths / 10 if o.settings.away.tenths is not None else None)),
    "deadband": Feature(read_supported=True, command=controls.policy(
        controls.deadband_command, lambda o: o.settings.deadband.tenths / 10 if o.settings.deadband.tenths is not None else None)),
    "lower_temperature_limit": Feature(read_supported=True, command=controls.policy(
        controls.lower_limit_command, lambda o: o.settings.limits.lower.value)),
    "upper_temperature_limit": Feature(read_supported=True, command=controls.policy(
        controls.upper_limit_command, lambda o: o.settings.limits.upper.value)),
    **{f"general_schedule_{slot}": Feature(read_supported=True, command=controls.policy(
        lambda snapshot, enabled, slot=slot: controls.general_slot_command(snapshot, slot, enabled))) for slot in range(10)},
    **{f"periodic_schedule_{bank}": Feature(read_supported=True, command=controls.policy(
        lambda snapshot, enabled, bank=bank: controls.periodic_bank_command(snapshot, bank, enabled))) for bank in range(2)},
}


@dataclass(frozen=True)
class Prepared:
    """One runtime's composed definitions and firmware/layout metadata for Diagnostics.

    Both definitions attach the packed-summary room commands. `definition` also attaches the extension
    commands when the firmware is eligible; `baseline` shares its decoder without them and is published
    for snapshots outside the qualified context.
    """

    firmware: str | None
    version: tuple[int, int] | None
    schedule_layout: schedule.Layout | None
    definition: DeviceDefinition
    baseline: DeviceDefinition


def prepare(firmware: str | None) -> Prepared:
    """Resolve firmware once; static support and the decoder share that one decision.

    Live single-room, value and stored-entry guards remain in observation/controls.
    """
    version = observation.firmware_version(firmware)
    layout = schedule.schedule_format(version)
    eligible = version is not None and version[0] == _CONTROL_FIRMWARE_MAJOR and version[1] >= _CONTROL_FIRMWARE_MIN_MINOR
    decode = partial(observation.decode_summary, controls_eligible=eligible, schedule_layout=layout)
    baseline = DeviceDefinition(decode=decode, features=_ROOM_FEATURES)
    extended = DeviceDefinition(decode=decode, features={**_ROOM_FEATURES, **_FEATURES}) if eligible else baseline
    return Prepared(firmware, version, layout, extended, baseline)


def resolve(registers: Sequence[int], prepared: Prepared) -> DeviceDefinition:
    """Attach extension commands only while firmware eligibility and this snapshot's single-room guard both hold.

    The guard is the observation's own decision; command policies still recheck the transaction-start state.
    """
    if prepared.definition is not prepared.baseline and observation.decode(registers).single_room_selected:
        return prepared.definition
    return prepared.baseline
