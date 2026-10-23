"""CCM Home Assistant presentation owner."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import Platform

from .registration import FamilyRegistration
from ..const import ICON_POWER_SOCKET
from ..devices import ccm as ccm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntity
from ..runtime import SihasRuntime


class Ccm300(SihasEntity, SwitchEntity):
    """CCM-300: a physical smart power outlet/plug (on/off plus voltage/current/power/
    power_factor attributes), matching `SwitchDeviceClass.OUTLET` exactly.
    """

    _attr_icon = ICON_POWER_SOCKET
    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='switch')

    @property
    def is_on(self):
        return self._state

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.commands.async_execute("power", True)

    async def async_turn_off(self, **kwargs):
        await self.runtime.commands.async_execute("power", False)

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._state = state.powered
        self._attributes[SensorDeviceClass.VOLTAGE] = state.voltage
        self._attributes[SensorDeviceClass.CURRENT] = state.current
        self._attributes[SensorDeviceClass.POWER] = state.power
        self._attributes[SensorDeviceClass.POWER_FACTOR] = state.power_factor


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(ccm_semantics.DEFINITION)),
    entities={Platform.SWITCH: lambda runtime: [Ccm300(runtime)]},
)
