"""Platform for select integration — BCM-300 Season 2."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from typing import Final

from homeassistant.components.select import SelectEntity

from .devices.bcm import state as bcm
from .entity import SihasEntity
from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    SIHAS_PLATFORM_SCHEMA,
)

SCAN_INTERVAL = timedelta(seconds=5)
PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES
PLATFORM_SCHEMA = SIHAS_PLATFORM_SCHEMA


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "BCM":
        async_add_entities([BcmOccupancySelect(runtime)])


class BcmOccupancySelect(SihasEntity, SelectEntity):
    """BCM-300 occupancy select: home / away (reg[5])."""

    _attr_options: Final = [bcm.OCCUPANCY_HOME, bcm.OCCUPANCY_AWAY]

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='occupancy', translation_key='occupancy')

    async def async_select_option(self, option: str) -> None:
        await self.runtime.commands.async_bcm_occupancy(option)

    def _project_state(self) -> None:
        self._attr_current_option = bcm.OCCUPANCY_AWAY if self.coordinator.data.state.away else bcm.OCCUPANCY_HOME
