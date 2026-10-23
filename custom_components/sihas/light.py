"""Platform for light integration."""

from __future__ import annotations

from typing import List

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES, ICON_LIGHT_BULB
from .entity import family_entities, SihasEntityGroup, SihasProjection
from .runtime import SihasConfigEntry

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(family_entities(entry.runtime_data, Platform.LIGHT))


class StmSbm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        # The family-typed state holds exactly the configured channels.
        return [StmSbmVirtualLight(self, i) for i in range(len(self.runtime.coordinator.data.state))]


class StmSbmVirtualLight(SihasProjection, LightEntity):
    _attr_icon = ICON_LIGHT_BULB

    def __init__(self, stbm: StmSbm300, number_of_switch: int):
        super().__init__(stbm.runtime, entity_key=f"channel_{number_of_switch}", translation_key="channel",
                         translation_placeholders={"number": str(number_of_switch + 1)})

        self._state = None
        self._number_of_switch = number_of_switch
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self):
        return self._state

    def _project_state(self):
        self._state = self.coordinator.data.state[self._number_of_switch]

    async def async_turn_on(self, **kwargs):
        await self.runtime.commands.async_execute(f"channel_{self._number_of_switch}", True)

    async def async_turn_off(self, **kwargs):
        await self.runtime.commands.async_execute(f"channel_{self._number_of_switch}", False)
