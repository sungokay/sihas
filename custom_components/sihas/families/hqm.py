"""HQM Home Assistant presentation owner."""
from __future__ import annotations

import logging
from typing import cast, Final, List

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import ATTR_TEMPERATURE, PERCENTAGE, Platform, UnitOfTemperature
from homeassistant.helpers.entity import Entity

from .registration import FamilyRegistration
from ..climate import ROOM_SUPPORTED_FEATURES
from ..const import ICON_HEATER
from ..devices import hqm as hqm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntity, SihasEntityGroup, SihasProjection
from ..runtime import SihasRuntime

_LOGGER = logging.getLogger(__name__)


class Hqm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        state = self.runtime.coordinator.data.state
        if state.standalone is not None:
            return [HqmStandaloneThermostat(self)]
        return [HqmVirtualThermostat(self, i) for i in range(len(state.rooms))]


class HqmVirtualThermostat(SihasProjection, ClimateEntity):
    _attr_icon = ICON_HEATER
    _attr_hvac_modes: Final = [HVACMode.OFF, HVACMode.HEAT]
    _attr_max_temp = 65
    _attr_min_temp: Final = 0
    _attr_supported_features: Final = ROOM_SUPPORTED_FEATURES
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS

    def __init__(self, group: Hqm300, number_of_room: int) -> None:
        super().__init__(group.runtime, entity_key=f"room_{number_of_room}", translation_key="room",
                         translation_placeholders={"number": str(number_of_room + 1)})
        self._number_of_room = number_of_room

    @property
    def room_state(self):
        return self.coordinator.data.state.rooms[self._number_of_room]

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


class HqmStandaloneThermostat(SihasProjection, ClimateEntity):
    _attr_icon = ICON_HEATER
    _attr_hvac_modes: Final = [HVACMode.OFF, HVACMode.HEAT]
    _attr_max_temp = 65
    _attr_min_temp: Final = 0
    _attr_supported_features: Final = ROOM_SUPPORTED_FEATURES
    _attr_target_temperature_step = 0.1
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS

    def __init__(self, group: Hqm300) -> None:
        super().__init__(group.runtime, entity_key="climate")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        if hvac_mode not in (HVACMode.OFF, HVACMode.HEAT):
            _LOGGER.error("Not supported HVACMode for HQM-300: %s", hvac_mode)
            return
        await self.runtime.commands.async_execute("power", hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_execute("temperature", cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self):
        state = self.coordinator.data.state.standalone
        self._attr_hvac_mode = HVACMode.HEAT if state.powered else HVACMode.OFF
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature
        if state.action is None:
            _LOGGER.warning("Not implemented HVAC actions (%s, %s)", state.raw_power, state.raw_valve)
        else:
            self._attr_hvac_action = HVACAction(state.action)


class HqmHumidSensor(SihasEntity, SensorEntity):

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='humidity', translation_key='humidity')
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT

    def _project_state(self) -> None:
        self._attr_native_value = self.coordinator.data.state.humidity


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(hqm_semantics.definition(config))),
    entities={
        Platform.CLIMATE: lambda runtime: Hqm300(runtime).get_sub_entities(),
        Platform.SENSOR: lambda runtime: [HqmHumidSensor(runtime)],
    },
)
