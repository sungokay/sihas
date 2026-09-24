"""Platform for number integration."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Final

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.hvm import controls as hvm_controls
from .devices.hvm import observation as hvm_observation
from .entity import SihasProjection
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES: Final = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "HVM" and runtime.coordinator.data.state.controls_qualified:
        async_add_entities(hvm_numbers(runtime))


class HvmSettingNumber(SihasProjection, NumberEntity):
    """Device-level HVM setting projected from the published observation.

    min/max/step are the family-owned public capability range, which may depend
    on the current readback (temperature limits). Without a range the entity is
    unavailable. The value is always the refreshed readback; a readback outside
    the range is still shown as observed and never widens the writable range.
    No device class is set so HA never converts these exact Celsius values or
    temperature differences.
    """

    _attr_entity_category = EntityCategory.CONFIG
    diagnostic_generated_attributes = frozenset({"min", "max", "step"})

    def __init__(self, runtime: SihasRuntime, key: str, unit: str,
                 capability: Callable[[hvm_observation.HvmObservation], hvm_controls.NumberRange | None], command,
                 reading: Callable[[hvm_observation.HvmObservation], int | float | None], *, enabled_default: bool) -> None:
        super().__init__(runtime, entity_key=key, translation_key=key)
        # Entity Registry creation default only; HA keeps a user's later choice.
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_native_unit_of_measurement = unit
        self._capability = capability
        self._command = command
        self._reading = reading

    @property
    def available(self) -> bool:
        state = self.coordinator.data.state if self.coordinator.data is not None else None
        return super().available and state.controls_qualified and self._capability(state.observation) is not None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.runtime.commands.async_snapshot_write(partial(self._command, value=value))
        except ValueError as err:
            # Family selectors reject before any device I/O.
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        observed = self.coordinator.data.state.observation
        self._attr_native_value = self._reading(observed)
        if (capability := self._capability(observed)) is not None:
            self._attr_native_min_value = float(capability.minimum)
            self._attr_native_max_value = float(capability.maximum)
            self._attr_native_step = float(capability.increment)


def _fixed(capability: hvm_controls.NumberRange):
    return lambda observed: capability


def _celsius(temperature: hvm_observation.Temperature) -> float | None:
    return float(temperature.celsius) if temperature.celsius is not None else None


def hvm_numbers(runtime: SihasRuntime) -> list[HvmSettingNumber]:
    """R8 compensation, R9 ON minutes, R11 away temperature, R14 deadband and R13/R12 limits."""
    celsius = UnitOfTemperature.CELSIUS
    return [
        HvmSettingNumber(runtime, "temperature_compensation", celsius, _fixed(hvm_controls.COMPENSATION_RANGE), hvm_controls.compensation_command,
                         lambda observed: _celsius(observed.settings.compensation), enabled_default=False),
        HvmSettingNumber(runtime, "on_minutes", UnitOfTime.MINUTES, _fixed(hvm_controls.ON_MINUTES_RANGE), hvm_controls.on_minutes_command,
                         lambda observed: observed.detail.on_minutes.value, enabled_default=False),
        HvmSettingNumber(runtime, "away_temperature", celsius, _fixed(hvm_controls.AWAY_RANGE), hvm_controls.away_command,
                         lambda observed: _celsius(observed.settings.away), enabled_default=True),
        HvmSettingNumber(runtime, "deadband", celsius, _fixed(hvm_controls.DEADBAND_RANGE), hvm_controls.deadband_command,
                         lambda observed: _celsius(observed.settings.deadband), enabled_default=False),
        HvmSettingNumber(runtime, "lower_temperature_limit", celsius, hvm_controls.lower_limit_range, hvm_controls.lower_limit_command,
                         lambda observed: observed.settings.limits.lower.value, enabled_default=False),
        HvmSettingNumber(runtime, "upper_temperature_limit", celsius, hvm_controls.upper_limit_range, hvm_controls.upper_limit_command,
                         lambda observed: observed.settings.limits.upper.value, enabled_default=False),
    ]
