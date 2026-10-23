"""Platform for number integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.controls import NumberRange
from .devices.state import DeviceSnapshot
from .entity import family_entities, SihasProjection
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES: Final = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(family_entities(entry.runtime_data, Platform.NUMBER))


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
