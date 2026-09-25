"""Platform for number integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, Final

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.bcm import controls as bcm_controls
from .devices.controls import NumberRange
from .devices.hvm import controls as hvm_controls
from .devices.hvm import observation as hvm_observation
from .devices.state import DeviceSnapshot
from .entity import SihasProjection, definition_can_write
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES: Final = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "BCM":
        async_add_entities(bcm_numbers(runtime))
    elif runtime.device.device_type == "HVM" and runtime.coordinator.data.state.controls_qualified:
        async_add_entities(hvm_numbers(runtime))


class SihasControlNumber(SihasProjection, NumberEntity):
    """Device control number shared by device families.

    min/max/step are the family-owned public capability range, which may depend
    on the current readback. Without a range the entity is unavailable and the
    family selector rejects writes. The value is always the refreshed readback;
    a readback outside the range is still shown as observed and never widens the
    writable range. No device class is set so HA never converts these exact
    Celsius values or temperature differences.
    """

    diagnostic_generated_attributes = frozenset({"min", "max", "step"})

    def __init__(self, runtime: SihasRuntime, key: str, unit: str, *, supported: Callable[[DeviceSnapshot], bool],
                 capability: Callable[[Any], NumberRange | None], reading: Callable[[Any], int | float | None],
                 write: Callable[[float], Awaitable[None]], category: EntityCategory | None = EntityCategory.CONFIG,
                 enabled_default: bool = False) -> None:
        super().__init__(runtime, entity_key=key, translation_key=key)
        self._attr_entity_category = category
        # Entity Registry creation default only; HA keeps a user's later choice.
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_native_unit_of_measurement = unit
        self._supported = supported
        self._capability = capability
        self._reading = reading
        self._write = write

    @property
    def available(self) -> bool:
        snapshot = self.coordinator.data
        return super().available and self._supported(snapshot) and self._capability(snapshot.state) is not None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._write(value)
        except ValueError as err:
            # Family selectors reject before any device I/O.
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_native_value = self._reading(state)
        if (capability := self._capability(state)) is not None:
            self._attr_native_min_value = float(capability.minimum)
            self._attr_native_max_value = float(capability.maximum)
            self._attr_native_step = float(capability.increment)


def _celsius(temperature: hvm_observation.Temperature) -> float | None:
    return float(temperature.celsius) if temperature.celsius is not None else None


def hvm_numbers(runtime: SihasRuntime) -> list[SihasControlNumber]:
    """R8 compensation, R9 ON minutes, R11 away temperature, R14 deadband and R13/R12 limits."""
    def number(key: str, unit: str, capability, command, reading, *, enabled_default: bool) -> SihasControlNumber:
        return SihasControlNumber(
            runtime, key, unit, supported=lambda snapshot: snapshot.state.controls_qualified,
            capability=lambda state: capability(state.observation), reading=lambda state: reading(state.observation),
            write=lambda value: runtime.commands.async_snapshot_write(partial(command, value=value)), enabled_default=enabled_default,
        )

    def fixed(capability: NumberRange):
        return lambda observed: capability

    celsius = UnitOfTemperature.CELSIUS
    return [
        number("temperature_compensation", celsius, fixed(hvm_controls.COMPENSATION_RANGE), hvm_controls.compensation_command,
               lambda observed: _celsius(observed.settings.compensation), enabled_default=False),
        number("on_minutes", UnitOfTime.MINUTES, fixed(hvm_controls.ON_MINUTES_RANGE), hvm_controls.on_minutes_command,
               lambda observed: observed.detail.on_minutes.value, enabled_default=False),
        number("away_temperature", celsius, fixed(hvm_controls.AWAY_RANGE), hvm_controls.away_command,
               lambda observed: _celsius(observed.settings.away), enabled_default=True),
        number("deadband", celsius, fixed(hvm_controls.DEADBAND_RANGE), hvm_controls.deadband_command,
               lambda observed: _celsius(observed.settings.deadband), enabled_default=False),
        number("lower_temperature_limit", celsius, hvm_controls.lower_limit_range, hvm_controls.lower_limit_command,
               lambda observed: observed.settings.limits.lower.value, enabled_default=False),
        number("upper_temperature_limit", celsius, hvm_controls.upper_limit_range, hvm_controls.upper_limit_command,
               lambda observed: observed.settings.limits.upper.value, enabled_default=False),
    ]


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
