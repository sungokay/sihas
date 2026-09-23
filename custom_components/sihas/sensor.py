from __future__ import annotations
from dataclasses import dataclass

from datetime import timedelta
from typing import Callable, Dict, List

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfDensity,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from typing_extensions import Final

from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    ICON_POWER_METER,
    SIHAS_PLATFORM_SCHEMA,
)
from .devices.state import DeviceState
from .entity import SihasEntity, SihasEntityGroup, SihasProjection

SCAN_INTERVAL = timedelta(seconds=10)

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES
PLATFORM_SCHEMA = SIHAS_PLATFORM_SCHEMA


@dataclass(frozen=True, kw_only=True)
class SihasSensorEntityDescription(SensorEntityDescription):
    """`SensorEntityDescription` plus a projection from the device-owned state.

    `key` is always the stable `entity_key`; it carries no other meaning and
    must never be derived from `device_class`, unit, or any other metadata field here.
    """

    value_handler: Callable[[DeviceState], int | float]


AQM_SENSOR_DESCRIPTIONS: Final[Dict[str, SihasSensorEntityDescription]] = {
    "humidity": SihasSensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.humidity,
    ),
    "temperature": SihasSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.temperature,
    ),
    "illuminance": SihasSensorEntityDescription(
        key="illuminance",
        translation_key="illuminance",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.illuminance,
    ),
    "co2": SihasSensorEntityDescription(
        key="co2",
        translation_key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.co2,
    ),
    "pm25": SihasSensorEntityDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.pm25,
    ),
    "pm10": SihasSensorEntityDescription(
        key="pm10",
        translation_key="pm10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.pm10,
    ),
    "tvoc": SihasSensorEntityDescription(
        key="tvoc",
        translation_key="tvoc",
        # ppb is a valid unit for this device class.
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_BILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_handler=lambda state: state.tvoc,
    ),
}

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
        # Resets each calendar month: a period total, not a monotonically increasing lifetime counter.
        state_class=SensorStateClass.TOTAL,
        value_handler=lambda state: state.this_month_energy,
    ),
    PMM_KEY_THIS_DAY_ENERGY: SihasSensorEntityDescription(
        key=PMM_KEY_THIS_DAY_ENERGY,
        translation_key=PMM_KEY_THIS_DAY_ENERGY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # Resets each day: a period total, not a monotonically increasing lifetime counter.
        state_class=SensorStateClass.TOTAL,
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
        # A closed, immutable prior-month total: reported as TOTAL, matching this_month/this_day.
        state_class=SensorStateClass.TOTAL,
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


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    match runtime.device.device_type:
        case "PMM":
            async_add_entities(Pmm300(runtime).get_sub_entities())
        case "AQM":
            async_add_entities(Aqm300(runtime).get_sub_entities())
        case "HQM":
            async_add_entities([HqmHumidSensor(runtime)])
        case "BCM":
            entities = [BcmWaterStatusSensor(runtime)]
            snapshot = runtime.coordinator.data
            if snapshot is not None and snapshot.definition is not None:
                for sensor_type in (BcmHotWaterLevelSensor, BcmTimerSettingSensor):
                    sensor = sensor_type(runtime)
                    if sensor.available:
                        entities.append(sensor)
            async_add_entities(entities)


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


class Aqm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        return [
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["co2"]),
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["pm25"]),
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["pm10"]),
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["tvoc"]),
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["humidity"]),
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["illuminance"]),
            AqmVirtualSensor(self, AQM_SENSOR_DESCRIPTIONS["temperature"]),
        ]


class AqmVirtualSensor(SihasProjection, SensorEntity):
    entity_description: SihasSensorEntityDescription

    def __init__(self, group: Aqm300, description: SihasSensorEntityDescription) -> None:
        super().__init__(group.runtime, entity_key=description.key)
        self.entity_description = description

    def _project_state(self):
        self._attr_native_value = self.entity_description.value_handler(self.coordinator.data.state)


class HqmHumidSensor(SihasEntity, SensorEntity):

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='humidity', translation_key='humidity')
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT

    def _project_state(self) -> None:
        self._attr_native_value = self.coordinator.data.state.humidity


class BcmWaterStatusSensor(SihasEntity, SensorEntity):
    """BCM-300 water-pressure/status sensor (reg[13]: 0=normal, 1=needs_refill, other=unknown)."""

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='water_status', translation_key='water_status')

    def _project_state(self) -> None:
        # Only reg[13]=0 (normal) and reg[13]=1 (needs_refill) are protocol-qualified.
        # Any other value is reported as "unknown" — never silently mapped to normal.
        self._attr_native_value = self.coordinator.data.state.water_status


class BcmHotWaterLevelSensor(SihasEntity, SensorEntity):
    """Read-qualified levels retain their semantic identity when applicability changes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["low", "high"]

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key="hot_water_level", translation_key="hot_water_level")

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snapshot = self.coordinator.data
        feature = snapshot.definition.features.get(self.entity_key) if snapshot.definition is not None else None
        setting = snapshot.state.hot_water
        return bool(feature and feature.read_supported and setting.read_qualified and setting.kind == "level" and setting.quality == "valid")

    def _project_state(self) -> None:
        setting = self.coordinator.data.state.hot_water
        self._attr_native_value = setting.value if self.available else None
        self._attributes = {"raw": setting.raw, "quality": setting.quality}


class BcmTimerSettingSensor(SihasEntity, SensorEntity):
    """Read-only periodic timer display; it does not represent timer enable state."""

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key="timer_setting", translation_key="timer_setting")

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snapshot = self.coordinator.data
        feature = snapshot.definition.features.get(self.entity_key) if snapshot.definition is not None else None
        setting = snapshot.state.timer
        return bool(feature and feature.read_supported and setting.read_qualified and setting.quality == "valid")

    def _project_state(self) -> None:
        setting = self.coordinator.data.state.timer
        self._attr_native_value = f"{setting.period_hours}h / {setting.run_minutes}m" if self.available else None
        self._attributes = {"raw": setting.raw, "quality": setting.quality,
                            "period_hours": setting.period_hours, "run_minutes": setting.run_minutes}
