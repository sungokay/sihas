from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.controls import StoredToggle, toggle_offered
from .devices.state import DeviceSnapshot
from .entity import family_entities, SihasProjection
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(family_entities(entry.runtime_data, Platform.SWITCH))


class SihasControlSwitch(SihasProjection, SwitchEntity):
    """Device control switch shared by device families.

    For a stored manufacturer-owned entry the switch is only its enable bit:
    the raw word is sufficient for state and write, and decoded fields are
    optional read-only attributes that are omitted when they do not decode. The
    manufacturer app remains the editor for every other field. Available only
    while `supported` holds for the current publication, always projecting
    refreshed readback. Config category and default-disabled Entity Registry
    creation follow the shared policy; HA keeps a user's later choice.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    diagnostic_generated_attributes = frozenset({
        "kind", "month", "day", "weekdays", "repeat", "hour", "minute", "mode", "preserve_value", "temperature", "time_minutes",
        "start_hour", "end_hour", "period_hours", "on_minutes", "active_temperature", "end_action",
        "timer_period_hours", "timer_run_minutes", "hot_water_level", "run_minutes", "temperature_control",
    })

    def __init__(self, runtime: SihasRuntime, key: str, *, supported: Callable[[DeviceSnapshot], bool],
                 reading: Callable[[Any], tuple[bool | None, dict[str, Any]]], write: Callable[[bool], Awaitable[None]],
                 index: int | None = None) -> None:
        super().__init__(runtime, entity_key=key if index is None else f"{key}_{index}", translation_key=key,
                         translation_placeholders=None if index is None else {"number": str(index + 1)})
        self._supported = supported
        self._reading = reading
        self._write = write

    @property
    def available(self) -> bool:
        return super().available and self._supported(self.coordinator.data)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_enable(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_enable(False)

    async def _async_enable(self, enabled: bool) -> None:
        try:
            await self._write(enabled)
        except ValueError as err:
            # The family selector rejects before any device I/O.
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        self._attr_is_on, self._attr_extra_state_attributes = self._reading(self.coordinator.data.state)


def toggle_reading(toggle: StoredToggle | None, attributes: Callable[[], dict[str, Any]]) -> tuple[bool | None, dict[str, Any]]:
    return (toggle.enabled, attributes()) if toggle_offered(toggle) else (None, {})
