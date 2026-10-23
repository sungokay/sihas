"""BCM Home Assistant presentation owner."""
from __future__ import annotations

from functools import partial
from typing import Any, cast, Final

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import ATTR_TEMPERATURE, EntityCategory, Platform, UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError

from .registration import FamilyRegistration
from ..const import ICON_HEATER
from ..devices.bcm import (
    controls as bcm_controls,
    definition as bcm_definition,
    metadata as bcm_metadata,
    settings as bcm_settings,
    state as bcm,
)
from ..devices.bcm.diagnostics import decode_diagnostics
from ..devices.controls import toggle_offered
from ..devices.state import DeviceBinding, DeviceSnapshot
from ..entity import definition_can_write, SihasEntity
from ..number import SihasControlNumber
from ..runtime import SihasRuntime
from ..select import SihasControlSelect
from ..switch import toggle_reading, SihasControlSwitch


class BcmProblemSensor(SihasEntity, BinarySensorEntity):
    """BCM-300 boiler problem/error binary sensor (reg[12]: 0=normal, non-zero=error).

    is_on=True means a problem exists (BinarySensorDeviceClass.PROBLEM semantics).
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='problem', translation_key='problem')

    def _project_state(self) -> None:
        self._attr_is_on = self.coordinator.data.state.problem


class BcmConnectivitySensor(SihasEntity, BinarySensorEntity):
    """BCM-300 device-reported connectivity binary sensor (reg[14]: 0=online, 1=offline).

    is_on=True means the boiler reports itself as connected/online.
    Device-reported connectivity is distinct from HA entity availability.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='connectivity', translation_key='connectivity')

    def _project_state(self) -> None:
        # reg[14]: 0=online -> is_on=True; 1=offline -> is_on=False
        self._attr_is_on = self.coordinator.data.state.connected


class BcmBurnerSensor(SihasEntity, BinarySensorEntity):
    """BCM-300 generic burner/flame activity (reg[11]: 0=idle, non-zero=active).

    Burner activity also occurs for domestic hot water, so it is not presented as
    space heating and has no device class that would claim a narrower meaning.
    """

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='burner', translation_key='burner')

    def _project_state(self) -> None:
        self._attr_is_on = self.coordinator.data.state.burner


BCM_SUPPORTED_FEATURES: Final = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF


# Presentation range for controllers whose target carries no device-reported range; also the inert value without a target control.
BCM_FALLBACK_TEMPERATURES: Final = (0, 80)


class Bcm300(SihasEntity, ClimateEntity):
    """R0 power as OFF/HEAT, the controller-qualified preset axis and the projected target.

    Preset, target selection, range and action are decoded by the BCM family;
    this entity only projects them and forwards intents to the device definition.
    """

    _attr_icon = ICON_HEATER
    _attr_name = None
    _attr_translation_key = "boiler"
    _attr_hvac_modes: Final = [HVACMode.OFF, HVACMode.HEAT]
    _attr_target_temperature_step: Final = 1
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS
    diagnostic_generated_attributes = frozenset({"preset_mode", "preset_modes"})

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='climate')

    async def _async_execute(self, feature: str, value) -> None:
        try:
            await self.runtime.commands.async_execute(feature, value)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def async_set_hvac_mode(self, hvac_mode: str):
        if hvac_mode not in self._attr_hvac_modes:
            raise ServiceValidationError(f"Unsupported BCM HVAC mode: {hvac_mode}")
        await self._async_execute("power", hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self._async_execute("temperature", cast(float, kwargs.get(ATTR_TEMPERATURE)))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._async_execute("preset", preset_mode)

    def _project_state(self) -> None:
        snapshot = self.coordinator.data
        state = snapshot.state
        self._attr_hvac_mode = None if state.powered is None else HVACMode.HEAT if state.powered else HVACMode.OFF
        self._attr_hvac_action = None if state.action is None else HVACAction(state.action)
        self._attr_current_temperature = state.current_temperature
        features = BCM_SUPPORTED_FEATURES
        presets = definition_can_write(snapshot, "preset")
        if presets:
            features |= ClimateEntityFeature.PRESET_MODE
        self._attr_preset_modes = list(bcm.PRESETS) if presets else None
        self._attr_preset_mode = state.preset if presets else None
        target = state.target
        self._attr_min_temp, self._attr_max_temp = BCM_FALLBACK_TEMPERATURES
        if target is None:
            self._attr_target_temperature = None
        else:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
            self._attr_target_temperature = target.temperature
            if target.bounds is not None:
                self._attr_min_temp, self._attr_max_temp = target.bounds.minimum, target.bounds.maximum
        self._attr_supported_features = features


def _compensation(state) -> float | None:
    value = state.settings.compensation.value
    return float(value) if value is not None else None


def bcm_numbers(runtime: SihasRuntime) -> list[SihasControlNumber]:
    """Controller-qualified BCM targets and configuration, created when the first publication's definition attaches them."""
    def number(key: str, capability, reading, *, operational: bool = False) -> SihasControlNumber:
        # Operational targets keep no entity category; every BCM number is disabled at first Registry creation.
        return SihasControlNumber(
            runtime, key, UnitOfTemperature.CELSIUS, supported=partial(definition_can_write, feature=key), capability=capability,
            reading=reading, write=partial(runtime.commands.async_execute, key),
            category=None if operational else EntityCategory.CONFIG, enabled_default=False,
        )

    candidates = [
        number("room_target_temperature", bcm_controls.room_target_range, lambda state: state.room_target, operational=True),
        number("ondol_target_temperature", bcm_controls.ondol_target_range, lambda state: state.ondol_target, operational=True),
        number("temperature_compensation", lambda state: bcm_controls.COMPENSATION_RANGE, _compensation),
        number("room_upper_temperature_limit", bcm_controls.room_upper_limit_range, lambda state: state.limits.room.upper_raw),
        number("room_lower_temperature_limit", bcm_controls.room_lower_limit_range, lambda state: state.limits.room.lower_raw),
        number("ondol_upper_temperature_limit", bcm_controls.ondol_upper_limit_range, lambda state: state.limits.ondol.upper_raw),
        number("ondol_lower_temperature_limit", bcm_controls.ondol_lower_limit_range, lambda state: state.limits.ondol.lower_raw),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


def bcm_selects(runtime: SihasRuntime) -> list[SihasControlSelect]:
    """Controller-qualified BCM selects, created when the first publication's definition attaches their writers."""
    def select(key: str, options: list[str], reading, *, supported=None, **kwargs) -> SihasControlSelect:
        return SihasControlSelect(runtime, key, options, supported=supported or partial(definition_can_write, feature=key),
                                  reading=reading, write=partial(runtime.commands.async_execute, key), **kwargs)

    candidates = [
        select("operating_program", list(bcm.PROGRAMS), lambda state: state.program,
               attributes=bcm_controls.program_attributes, category=None, enabled_default=True),
        select("heating_level", list(bcm_controls.HEATING_LEVELS), lambda state: state.heating_level.value,
               category=None, enabled_default=True),
        select("backlight", list(bcm_controls.BACKLIGHT_OPTIONS),
               lambda state: bcm_controls.current_option(bcm_controls.BACKLIGHT_OPTIONS, state.settings.backlight.mode)),
        select("touch_lock", list(bcm_controls.TOUCH_LOCK_OPTIONS),
               lambda state: bcm_controls.current_option(bcm_controls.TOUCH_LOCK_OPTIONS, state.settings.touch_lock.mode)),
    ]
    # R21 fixes the level options at creation; another later representation makes the select unavailable.
    if (levels := runtime.coordinator.data.state.limits.hot_water.levels) is not None:
        def same_levels(snapshot: DeviceSnapshot) -> bool:
            return definition_can_write(snapshot, "hot_water_level") and snapshot.state.limits.hot_water.levels == levels

        candidates.append(select("hot_water_level", list(levels), bcm_controls.hot_water_level, supported=same_levels,
                                 category=None, enabled_default=True))
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


class BcmWaterStatusSensor(SihasEntity, SensorEntity):
    """BCM-300 water-pressure/status sensor (reg[13]: 0=normal, 1=needs_refill, other=unknown)."""

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='water_status', translation_key='water_status')

    def _project_state(self) -> None:
        # Only reg[13]=0 (normal) and reg[13]=1 (needs_refill) are protocol-qualified.
        # Any other value is reported as "unknown" — never silently mapped to normal.
        self._attr_native_value = self.coordinator.data.state.water_status


def bcm_switches(runtime: SihasRuntime) -> list[SihasControlSwitch]:
    """Controller-qualified R62 buzzer, general schedule slots and interval-repeat enable."""
    def supported(key: str, toggle=None):
        def check(snapshot: DeviceSnapshot) -> bool:
            return definition_can_write(snapshot, key) and (toggle is None or toggle_offered(toggle(snapshot.state)))
        return check

    def buzzer(state) -> tuple[bool | None, dict[str, Any]]:
        mode = state.settings.buzzer.mode
        return (None if mode is None else mode is bcm_settings.Buzzer.ENABLED), {}

    candidates = [
        SihasControlSwitch(runtime, "buzzer", supported=supported("buzzer"), reading=buzzer,
                           write=partial(runtime.commands.async_execute, "buzzer")),
        *(SihasControlSwitch(
            runtime, "general_schedule", index=slot,
            supported=supported(f"general_schedule_{slot}", partial(bcm_controls.general_toggle, slot=slot)),
            reading=lambda state, slot=slot: toggle_reading(bcm_controls.general_toggle(state, slot),
                                                             lambda: bcm_controls.general_slot_attributes(state, slot)),
            write=partial(runtime.commands.async_execute, f"general_schedule_{slot}"),
        ) for slot in range(10)),
        SihasControlSwitch(runtime, "interval_repeat", supported=supported("interval_repeat", bcm_controls.interval_toggle),
                           reading=lambda state: toggle_reading(bcm_controls.interval_toggle(state),
                                                                 lambda: bcm_controls.interval_attributes(state)),
                           write=partial(runtime.commands.async_execute, "interval_repeat")),
    ]
    snapshot = runtime.coordinator.data
    return [entity for entity in candidates if definition_can_write(snapshot, entity.entity_key)]


def _prepare(config: int, firmware: str | None) -> DeviceBinding:
    prepared = bcm_definition.prepare(firmware)
    return DeviceBinding(partial(bcm_definition.resolve, prepared=prepared), prepared, bcm_metadata.display)


FAMILY = FamilyRegistration(
    prepare=_prepare,
    diagnostics=decode_diagnostics,
    entities={
        Platform.BINARY_SENSOR: lambda runtime: [BcmProblemSensor(runtime), BcmConnectivitySensor(runtime), BcmBurnerSensor(runtime)],
        Platform.CLIMATE: lambda runtime: [Bcm300(runtime)],
        Platform.NUMBER: bcm_numbers,
        Platform.SELECT: bcm_selects,
        Platform.SENSOR: lambda runtime: [BcmWaterStatusSensor(runtime)],
        Platform.SWITCH: bcm_switches,
    },
)
