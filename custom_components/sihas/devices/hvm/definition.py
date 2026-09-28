"""HVM setup preparation and extension command-capability composition."""
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from ..definition import DeviceDefinition, Feature
from . import controls, observation, schedule

# Exact firmware of the observed single-room installation bounding provisional controls.
_CONTROL_FIRMWARE = (3, 33)
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
    """One runtime's composed definition and firmware/layout metadata for Diagnostics."""

    firmware: str | None
    version: tuple[int, int] | None
    schedule_layout: schedule.Layout | None
    definition: DeviceDefinition


def prepare(firmware: str | None) -> Prepared:
    """Resolve firmware once; static support and the decoder share that one decision.

    Live single-room, value and stored-entry guards remain in observation/controls.
    Legacy packed-summary room commands are not part of this extension definition.
    """
    version = observation.firmware_version(firmware)
    layout = schedule.schedule_format(version)
    eligible = version == _CONTROL_FIRMWARE
    definition = DeviceDefinition(
        decode=partial(observation.decode_summary, controls_eligible=eligible, schedule_layout=layout),
        features=_FEATURES if eligible else {},
    )
    return Prepared(firmware, version, layout, definition)


def resolve(registers: Sequence[int], prepared: Prepared) -> DeviceDefinition:
    """Retain static command support while the decoded snapshot supplies current usability."""
    return prepared.definition
