"""PMM Home Assistant presentation owner."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.helpers.entity import Entity
from typing_extensions import Final

from .registration import FamilyRegistration
from ..const import ICON_POWER_METER
from ..devices import pmm as pmm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntityGroup, SihasProjection
from ..sensor import SihasSensorEntityDescription


PMM_KEY_POWER: Final = "power"


PMM_KEY_THIS_MONTH_ENERGY: Final = "this_month_energy"


PMM_KEY_THIS_DAY_ENERGY: Final = "this_day_energy"


PMM_KEY_TOTAL: Final = "total_energy"


PMM_KEY_LAST_MONTH_ENERGY: Final = "last_month_energy"


PMM_KEY_VOLTAGE: Final = "voltage"


PMM_KEY_CURRENT: Final = "current"


PMM_KEY_POWER_FACTOR: Final = "power_factor"


PMM_KEY_FREQUENCY: Final = "frequency"


PMM_SENSOR_DESCRIPTIONS: Final[Dict[str, SihasSensorEntityDescription]] = {
    PMM_KEY_POWER: SihasSensorEntityDescription(
        key=PMM_KEY_POWER,
        translation_key=PMM_KEY_POWER,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.power,
    ),
    PMM_KEY_THIS_MONTH_ENERGY: SihasSensorEntityDescription(
        key=PMM_KEY_THIS_MONTH_ENERGY,
        translation_key=PMM_KEY_THIS_MONTH_ENERGY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # Increases within each calendar month and resets at the boundary; the reset is a new cycle, not a negative delta.
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_handler=lambda state: state.this_month_energy,
    ),
    PMM_KEY_THIS_DAY_ENERGY: SihasSensorEntityDescription(
        key=PMM_KEY_THIS_DAY_ENERGY,
        translation_key=PMM_KEY_THIS_DAY_ENERGY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # Increases within each day and resets at the boundary; the reset is a new cycle, not a negative delta.
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_handler=lambda state: state.this_day_energy,
    ),
    PMM_KEY_TOTAL: SihasSensorEntityDescription(
        key=PMM_KEY_TOTAL,
        translation_key=PMM_KEY_TOTAL,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # Lifetime cumulative energy: never decreases except on device reset.
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_handler=lambda state: state.total_energy,
    ),
    PMM_KEY_LAST_MONTH_ENERGY: SihasSensorEntityDescription(
        key=PMM_KEY_LAST_MONTH_ENERGY,
        translation_key=PMM_KEY_LAST_MONTH_ENERGY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # A closed prior-month snapshot, not a cumulative counter: no state_class, so no statistics deltas are accumulated.
        value_handler=lambda state: state.last_month_energy,
    ),
    PMM_KEY_VOLTAGE: SihasSensorEntityDescription(
        key=PMM_KEY_VOLTAGE,
        translation_key=PMM_KEY_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.voltage,
    ),
    PMM_KEY_CURRENT: SihasSensorEntityDescription(
        key=PMM_KEY_CURRENT,
        translation_key=PMM_KEY_CURRENT,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.current,
    ),
    PMM_KEY_POWER_FACTOR: SihasSensorEntityDescription(
        key=PMM_KEY_POWER_FACTOR,
        translation_key=PMM_KEY_POWER_FACTOR,
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.power_factor,
    ),
    PMM_KEY_FREQUENCY: SihasSensorEntityDescription(
        key=PMM_KEY_FREQUENCY,
        translation_key=PMM_KEY_FREQUENCY,
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.frequency,
    ),
}


class Pmm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        return [PmmVirtualSensor(self, description) for description in PMM_SENSOR_DESCRIPTIONS.values()]


class PmmVirtualSensor(SihasProjection, SensorEntity):
    _attr_icon = ICON_POWER_METER
    entity_description: SihasSensorEntityDescription

    def __init__(self, group: Pmm300, description: SihasSensorEntityDescription) -> None:
        super().__init__(group.runtime, entity_key=description.key)
        self.entity_description = description

    def _project_state(self):
        self._attr_native_value = self.entity_description.value_handler(self.coordinator.data.state)


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(pmm_semantics.DEFINITION)),
    poll_interval=timedelta(seconds=10),
    entities={Platform.SENSOR: lambda runtime: Pmm300(runtime).get_sub_entities()},
)
