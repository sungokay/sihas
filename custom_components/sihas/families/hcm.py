"""HCM Home Assistant presentation owner."""
from __future__ import annotations

from typing import cast, Final, List

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature
from homeassistant.helpers.entity import Entity

from .registration import FamilyRegistration
from ..climate import ROOM_SUPPORTED_FEATURES
from ..const import ICON_HEATER
from ..devices import hcm as hcm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntityGroup, SihasProjection


class Hcm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        return [HcmVirtualThermostat(self, i) for i in range(len(self.runtime.coordinator.data.state))]


class HcmVirtualThermostat(SihasProjection, ClimateEntity):
    _attr_icon = ICON_HEATER
    _attr_hvac_modes: Final = [HVACMode.OFF, HVACMode.HEAT]
    _attr_max_temp = 65
    _attr_min_temp: Final = 0
    _attr_supported_features: Final = ROOM_SUPPORTED_FEATURES
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS

    def __init__(self, group: Hcm300, number_of_room: int) -> None:
        super().__init__(group.runtime, entity_key=f"room_{number_of_room}", translation_key="room",
                         translation_placeholders={"number": str(number_of_room + 1)})
        self._number_of_room = number_of_room

    @property
    def room_state(self):
        return self.coordinator.data.state[self._number_of_room]

    async def async_set_hvac_mode(self, hvac_mode: str):
        await self.runtime.commands.async_execute(f"room_{self._number_of_room}_power", hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_execute(f"room_{self._number_of_room}_target", cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self):
        state = self.room_state
        # Preserve the existing presentation limit, including the whole-degree case.
        self._attr_max_temp = 65 if state.temperature_step == 0 else (65 / 2)
        self._attr_target_temperature_step = state.temperature_step
        self._attr_hvac_mode = HVACMode.HEAT if state.powered else HVACMode.OFF
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature
        self._attr_hvac_action = HVACAction.HEATING if state.valve_open else HVACAction.IDLE


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(hcm_semantics.DEFINITION)),
    # The initial topology read uses a single attempt; later polls use three.
    first_refresh_retry=1,
    entities={Platform.CLIMATE: lambda runtime: Hcm300(runtime).get_sub_entities()},
)
