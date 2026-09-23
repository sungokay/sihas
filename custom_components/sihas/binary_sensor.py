from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    SIHAS_PLATFORM_SCHEMA,
)
from .entity import SihasEntity

SCAN_INTERVAL = timedelta(seconds=10)

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES
PLATFORM_SCHEMA = SIHAS_PLATFORM_SCHEMA


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "ACM":
        async_add_entities([AcmVibrationSensor(runtime)])
    elif runtime.device.device_type == "BCM":
        async_add_entities([BcmProblemSensor(runtime), BcmConnectivitySensor(runtime)])


class AcmVibrationSensor(SihasEntity, BinarySensorEntity):
    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='vibration', translation_key='vibration')
        self._attr_device_class = BinarySensorDeviceClass.VIBRATION


    def _project_state(self) -> None:
        self._attr_is_on = self.coordinator.data.state.vibration


class BcmProblemSensor(SihasEntity, BinarySensorEntity):
    """BCM-300 boiler problem/error binary sensor (reg[12]: 0=normal, non-zero=error).

    is_on=True means a problem exists (BinarySensorDeviceClass.PROBLEM semantics).
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='problem', translation_key='problem')

    def _project_state(self) -> None:
        self._attr_is_on = self.coordinator.data.state.problem


class BcmConnectivitySensor(SihasEntity, BinarySensorEntity):
    """BCM-300 device-reported connectivity binary sensor (reg[14]: 0=online, 1=offline).

    is_on=True means the boiler reports itself as connected/online.
    Device-reported connectivity is distinct from HA entity availability.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='connectivity', translation_key='connectivity')

    def _project_state(self) -> None:
        # reg[14]: 0=online -> is_on=True; 1=offline -> is_on=False
        self._attr_is_on = self.coordinator.data.state.connected
