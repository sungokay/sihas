from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from typing_extensions import Final

from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    ICON_POWER_SOCKET,
    SIHAS_PLATFORM_SCHEMA,
)
from .entity import SihasEntity

SCAN_INTERVAL = timedelta(seconds=5)


PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES
PLATFORM_SCHEMA = SIHAS_PLATFORM_SCHEMA


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "CCM":
        async_add_entities([Ccm300(runtime)])
    elif runtime.device.device_type == "BCM":
        async_add_entities([BcmScheduleSwitch(runtime)])


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
        await self.runtime.commands.async_ccm_power(True)

    async def async_turn_off(self, **kwargs):
        await self.runtime.commands.async_ccm_power(False)

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._state = state.powered
        self._attributes[SensorDeviceClass.VOLTAGE] = state.voltage
        self._attributes[SensorDeviceClass.CURRENT] = state.current
        self._attributes[SensorDeviceClass.POWER] = state.power
        self._attributes[SensorDeviceClass.POWER_FACTOR] = state.power_factor


class BcmScheduleSwitch(SihasEntity, SwitchEntity):
    """BCM-300 schedule/timer mode switch (reg[6]: 0=disabled, 1=enabled)."""

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='schedule', translation_key='schedule')

    @property
    def is_on(self) -> bool | None:
        return self._state

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.commands.async_bcm_schedule(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.commands.async_bcm_schedule(False)

    def _project_state(self) -> None:
        self._state = self.coordinator.data.state.scheduled
