"""ACM Home Assistant presentation owner."""
from __future__ import annotations

from typing import cast

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    HVACMode,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
)
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature

from .registration import FamilyRegistration
from ..const import ICON_BUTTON, ICON_COOLER
from ..devices import acm as acm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntity, SihasProjection
from ..runtime import SihasRuntime


class AcmVibrationSensor(SihasEntity, BinarySensorEntity):
    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='vibration', translation_key='vibration')
        self._attr_device_class = BinarySensorDeviceClass.VIBRATION


    def _project_state(self) -> None:
        self._attr_is_on = self.coordinator.data.state.vibration


class AcmUCR(SihasProjection, ButtonEntity):
    _attr_icon = ICON_BUTTON

    def __init__(self, runtime: SihasRuntime, number_of_button: int):
        super().__init__(runtime, entity_key=f"ucr_{number_of_button}", translation_key="remote",
                         translation_placeholders={"number": str(number_of_button + 1)})
        self.number_of_button = number_of_button

    async def async_press(self) -> None:
        await self.runtime.commands.async_execute(f"remote_{self.number_of_button}", True)


class Acm300(SihasEntity, ClimateEntity):
    # base attribute
    _attr_icon = ICON_COOLER

    # entity attribute
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
        HVACMode.HEAT,
    ]
    _attr_max_temp = 30
    _attr_min_temp = 18
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_swing_modes = [
        SWING_OFF,
        SWING_VERTICAL,
        SWING_HORIZONTAL,
        SWING_BOTH,
    ]
    _attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO]


    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='climate')

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        await self.runtime.commands.async_execute("mode", hvac_mode)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_execute("temperature", cast(float, kwargs.get(ATTR_TEMPERATURE)))

    async def async_set_swing_mode(self, swing_mode):
        await self.runtime.commands.async_execute("swing", swing_mode)

    async def async_set_fan_mode(self, fan_mode):
        await self.runtime.commands.async_execute("fan", fan_mode)

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_hvac_mode = HVACMode(state.mode)
        self._attr_swing_mode = state.swing
        self._attr_fan_mode = state.fan
        if state.current_temperature is not None:
            self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(acm_semantics.definition(config))),
    entities={
        Platform.BINARY_SENSOR: lambda runtime: [AcmVibrationSensor(runtime)],
        Platform.BUTTON: lambda runtime: [AcmUCR(runtime, index) for index in runtime.coordinator.data.state.remote_buttons],
        Platform.CLIMATE: lambda runtime: [Acm300(runtime)],
    },
)
