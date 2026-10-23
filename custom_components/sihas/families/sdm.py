"""SDM Home Assistant presentation owner."""
from __future__ import annotations

from typing import List

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.const import Platform
from homeassistant.helpers.entity import Entity

from .registration import FamilyRegistration
from ..const import ICON_LIGHT_BULB
from ..devices import sdm
from ..devices.definition import fixed
from ..devices.numeric import normalize
from ..devices.state import DeviceBinding
from ..entity import SihasEntityGroup, SihasProjection


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
        self._attr_is_on = bool(state.power)
        self._attr_brightness = normalize(sdm.DIMMER_LEVEL_RANGE, (0, 255), state.level)

    async def async_turn_on(self, **kwargs):
        level = normalize((0, 255), sdm.DIMMER_LEVEL_RANGE, kwargs[ATTR_BRIGHTNESS]) if ATTR_BRIGHTNESS in kwargs else None
        await self.runtime.commands.async_execute(f"channel_{self._number_of_switch}", True if level is None else level)

    async def async_turn_off(self, **kwargs):
        await self.runtime.commands.async_execute(f"channel_{self._number_of_switch}", False)


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(sdm.definition(config))),
    entities={Platform.LIGHT: lambda runtime: Sdm300(runtime).get_sub_entities()},
)
