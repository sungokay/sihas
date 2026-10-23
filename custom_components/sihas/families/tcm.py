"""TCM Home Assistant presentation owner."""
from __future__ import annotations

from typing import cast, Final

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature

from .registration import FamilyRegistration
from ..const import ICON_HEATER
from ..devices import tcm
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntity
from ..runtime import SihasRuntime


class Tcm300(SihasEntity, ClimateEntity):
    _attr_icon = ICON_HEATER
    _attr_hvac_modes: Final = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    _attr_max_temp: Final = 80
    _attr_min_temp: Final = 0
    _attr_supported_features: Final = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step: Final = 0.1
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='climate')

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        await self.runtime.commands.async_execute("mode", hvac_mode)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_execute("temperature", cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_hvac_mode = HVACMode.OFF if not state.powered else (
            HVACMode.HEAT if state.mode == tcm.RunMode.HEATING else HVACMode.COOL
        )
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(tcm.DEFINITION)),
    entities={Platform.CLIMATE: lambda runtime: [Tcm300(runtime)]},
)
