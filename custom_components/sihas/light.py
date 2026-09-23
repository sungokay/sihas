"""Platform for light integration."""

from __future__ import annotations

from typing import List
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .runtime import SihasConfigEntry
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    ICON_LIGHT_BULB,
)
from .entity import SihasEntityGroup, SihasProjection
from .devices import sbm, sdm, sqm, stm
from .devices.numeric import normalize

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type in ("STM", "SBM", "SQM"):
        async_add_entities(StmSbm300(runtime).get_sub_entities())
    elif runtime.device.device_type == "SDM":
        async_add_entities(Sdm300(runtime).get_sub_entities())


class StmSbm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        if self.runtime.device.device_type == "STM":
            count = stm.switch_channel_count(self.runtime.device.config)
        elif self.runtime.device.device_type == "SBM":
            count = sbm.switch_channel_count(self.runtime.device.config)
        else:
            count = sqm.switch_channel_count(self.runtime.device.config)
        return [StmSbmVirtualLight(self, i) for i in range(0, count)]


class StmSbmVirtualLight(SihasProjection, LightEntity):
    _attr_icon = ICON_LIGHT_BULB

    def __init__(self, stbm: StmSbm300, number_of_switch: int):
        super().__init__(stbm.runtime, entity_key=f"channel_{number_of_switch}", translation_key="channel",
                         translation_placeholders={"number": str(number_of_switch + 1)})

        self._state = None
        self._number_of_switch = number_of_switch
        self._attr_supported_color_modes = [ColorMode.ONOFF]
        self._attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self):
        return self._state

    def _project_state(self):
        self._state = self.coordinator.data.state[self._number_of_switch]

    async def async_turn_on(self, **kwargs):
        await self.runtime.commands.async_light_power(self._number_of_switch, True)

    async def async_turn_off(self, **kwargs):
        await self.runtime.commands.async_light_power(self._number_of_switch, False)


class Sdm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        num_of_switches = sdm.dimmer_channel_count(self.runtime.device.config)
        return [SdmVirtualLight(self, i) for i in range(0, num_of_switches)]


class SdmVirtualLight(SihasProjection, LightEntity):
    _attr_icon = ICON_LIGHT_BULB

    def __init__(self, stbm: Sdm300, number_of_switch: int):
        super().__init__(stbm.runtime, entity_key=f"channel_{number_of_switch}", translation_key="channel",
                         translation_placeholders={"number": str(number_of_switch + 1)})

        self._number_of_switch = number_of_switch

    @property
    def color_mode(self):
        return ColorMode.BRIGHTNESS

    @property
    def supported_color_modes(self) -> set[str] | None:
        return {ColorMode.BRIGHTNESS}

    def _project_state(self):
        state = self.coordinator.data.state[self._number_of_switch]
        self._attr_is_on = state.power
        self._attr_brightness = normalize(sdm.DIMMER_LEVEL_RANGE, (0, 255), state.level)

    async def async_turn_on(self, **kwargs):
        level = normalize((0, 255), sdm.DIMMER_LEVEL_RANGE, kwargs[ATTR_BRIGHTNESS]) if ATTR_BRIGHTNESS in kwargs else None
        await self.runtime.commands.async_dimmer_on(self._number_of_switch, level)

    async def async_turn_off(self, **kwargs):
        await self.runtime.commands.async_dimmer_off(self._number_of_switch)
