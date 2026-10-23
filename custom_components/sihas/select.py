"""Platform for select integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.state import DeviceSnapshot
from .entity import family_entities, SihasProjection
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(family_entities(entry.runtime_data, Platform.SELECT))


class SihasControlSelect(SihasProjection, SelectEntity):
    """Device control select shared by device families.

    Available only while `supported` holds for the current publication. The
    selected option and attributes are always the refreshed readback; an unknown
    code has no option. The family selector rejects invalid requests before I/O.
    Entity category and the Entity Registry creation default follow the shared
    control policy; HA keeps a user's later enable/disable choice.
    """

    def __init__(self, runtime: SihasRuntime, key: str, options: list[str], *,
                 supported: Callable[[DeviceSnapshot], bool], reading: Callable[[Any], str | None],
                 write: Callable[[str], Awaitable[None]], attributes: Callable[[Any], dict[str, Any]] | None = None,
                 category: EntityCategory | None = EntityCategory.CONFIG, enabled_default: bool = False) -> None:
        super().__init__(runtime, entity_key=key, translation_key=key)
        self._attr_options = options
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled_default
        self._supported = supported
        self._reading = reading
        self._write = write
        self._attribute_reading = attributes
        self.diagnostic_generated_attributes = frozenset({"options"})

    @property
    def available(self) -> bool:
        return super().available and self._supported(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        try:
            await self._write(option)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_current_option = self._reading(state)
        if self._attribute_reading is not None:
            self._attr_extra_state_attributes = self._attribute_reading(state)
            self.diagnostic_generated_attributes = frozenset({"options", *self._attr_extra_state_attributes})
