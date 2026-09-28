"""BCM family-owned controller resolution and definition composition."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import cast

from . import controls, schedule, settings
from . import state as bcm
from ..definition import DeviceDefinition, Feature

_READ = Feature(read_supported=True)
# R0 power and the released R1/R2 climate target writer apply to every BCM controller.
_BASELINE_FEATURES = {
    "power": Feature(read_supported=True, command=controls.policy(controls.power_intents, command_list=False)),
    "temperature": Feature(read_supported=True, command=controls.policy(controls.temperature_intents, command_list=False)),
    "burner": _READ,
    "problem": _READ,
    "connectivity": _READ,
    "water_status": _READ,
    "controller_identity": _READ,
}
_KNOWN_FEATURES = {**_BASELINE_FEATURES, "limits": _READ, "timer_validation": _READ}


def _writer(select, *, command_list: bool, reading=None) -> Feature:
    return Feature(read_supported=True, command=controls.policy(select, command_list=command_list, reading=reading))


# Physical read evidence for this controller is recorded in docs/bcm-read-qualification.md.
# Its writers are provisional until physical write/readback qualification.
_VALIDATED_FEATURES = {
    **_KNOWN_FEATURES,
    "preset": _writer(controls.preset_intents, command_list=True,
                            reading=lambda s: s.preset),
    "operating_program": _writer(controls.program_intents, command_list=False),
    "room_target_temperature": _writer(controls.room_target_intents, command_list=False),
    "ondol_target_temperature": _writer(controls.ondol_target_intents, command_list=False),
    "heating_level": _writer(controls.heating_level_intents, command_list=True,
                            reading=lambda s: s.heating_level.value),
    "backlight": _writer(controls.backlight_intents, command_list=True,
                            reading=lambda s: controls.current_option(controls.BACKLIGHT_OPTIONS, s.settings.backlight.mode)),
    "temperature_compensation": _writer(controls.compensation_intents, command_list=True,
                            reading=lambda s: float(s.settings.compensation.value) if s.settings.compensation.value is not None else None),
    "room_upper_temperature_limit": _writer(controls.room_upper_limit_intents, command_list=True,
                            reading=lambda s: s.limits.room.upper_raw),
    "room_lower_temperature_limit": _writer(controls.room_lower_limit_intents, command_list=True,
                            reading=lambda s: s.limits.room.lower_raw),
    "ondol_upper_temperature_limit": _writer(controls.ondol_upper_limit_intents, command_list=True,
                            reading=lambda s: s.limits.ondol.upper_raw),
    "ondol_lower_temperature_limit": _writer(controls.ondol_lower_limit_intents, command_list=True,
                            reading=lambda s: s.limits.ondol.lower_raw),
    "touch_lock": _writer(controls.touch_lock_intents, command_list=True,
                            reading=lambda s: controls.current_option(controls.TOUCH_LOCK_OPTIONS, s.settings.touch_lock.mode)),
    "buzzer": _writer(controls.buzzer_intents, command_list=True,
                            reading=lambda s: s.settings.buzzer.mode is settings.Buzzer.ENABLED if s.settings.buzzer.mode is not None else None),
    **{f"general_schedule_{slot}": _writer(partial(controls.general_slot_intents, slot=slot), command_list=True) for slot in range(10)},
    "interval_repeat": _writer(controls.interval_intents, command_list=True),
}


def compose(features: Mapping[str, Feature], slots: bcm.SlotReader, *, known_encoding: bool = False,
            validated: bool = False) -> DeviceDefinition:
    """One controller composition: its support map and the decode choices of the same applicability."""
    return DeviceDefinition(decode=partial(bcm.decode, known_encoding=known_encoding, validated=validated, slots=slots),
                            features=features)


# Shared bundles, completed with a runtime's prepared schedule reader. Only the
# NR-5S/FR-5 bundle applies the validated projection and attaches its writers;
# the known-controller bundle adds only the app-static R21-R29 encoding reads.
BASELINE = partial(compose, _BASELINE_FEATURES)
KNOWN_CONTROLLER = partial(compose, _KNOWN_FEATURES, known_encoding=True)
VALIDATED = partial(compose, _VALIDATED_FEATURES, known_encoding=True, validated=True)
_BUNDLES = {bcm.BcmController.NR_5S_FR_5: VALIDATED, bcm.BcmController.NR_10E: KNOWN_CONTROLLER}


@dataclass(frozen=True)
class Prepared:
    """One runtime's firmware choices and controller definitions.

    `definitions` maps an evidenced (R15, R16) pair to its composition; any other
    identity uses `fallback`. The firmware text and components remain metadata.
    """

    firmware: str | None
    version: tuple[int, int] | None
    schedule_layout: schedule.Format | None
    definitions: Mapping[tuple[int, int], DeviceDefinition]
    fallback: DeviceDefinition


def prepare(firmware: str | None) -> Prepared:
    """Parse the configured firmware once and compose every known controller with its schedule reader.

    Writer composition is not firmware-gated; the version only selects the slot setting layout.
    """
    version = bcm.firmware_version(firmware)
    layout = schedule.schedule_format(version)
    slots = partial(schedule.decode_slots, layout=layout)
    return Prepared(firmware, version, layout,
                    {pair: _BUNDLES[controller](slots) for pair, controller in bcm.CONTROLLERS.items()}, BASELINE(slots))


def resolve(registers: bcm.Registers, prepared: Prepared) -> DeviceDefinition:
    """Select by the current R15/R16 words, never a nearest controller.

    Unmatched, missing or invalid identity retains raw identity and the fallback
    definition; it receives no known-controller range semantics or validated writers.
    """
    identity = bcm.identify(registers)
    if identity.quality not in ("valid", "unknown"):
        return prepared.fallback
    return prepared.definitions.get((identity.manufacturer_raw, identity.model_raw), prepared.fallback)


def decode(registers: bcm.Registers, prepared: Prepared) -> bcm.BcmState:
    """Keep the standalone family decoder entry point on this authority."""
    return cast(bcm.BcmState, resolve(registers, prepared).decode(registers))
