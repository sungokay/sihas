"""AQM Home Assistant presentation owner."""
from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Dict, Final, List

from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, LIGHT_LUX, PERCENTAGE, Platform, UnitOfDensity, UnitOfRatio, UnitOfTemperature
from homeassistant.helpers.entity import Entity, EntityCategory

from .registration import FamilyRegistration
from ..devices.aqm import controls as aqm_controls, definition as aqm_definition, link_toggle as aqm_link_toggle
from ..devices.aqm.actions import ACTION_INTENTS
from ..devices.aqm.diagnostics import decode_diagnostics, SENSITIVE_FIELDS
from ..devices.state import DeviceBinding, DeviceSnapshot
from ..entity import definition_can_write, SihasEntityGroup, SihasProjection
from ..number import SihasControlNumber
from ..runtime import SihasRuntime
from ..select import SihasControlSelect
from ..sensor import SihasSensorEntityDescription
from ..switch import SihasControlSwitch


class AqmAction(SihasProjection, ButtonEntity):
    """Stateless invocation; HA timestamps never imply device completion.

    Every AQM one-shot action is a configuration control, disabled at first
    Entity Registry creation; HA keeps a user's later enable/disable choice.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime: SihasRuntime, feature_key: str):
        if feature_key not in ACTION_INTENTS:
            raise ValueError("Unknown AQM action button")
        super().__init__(runtime, entity_key=feature_key, translation_key=feature_key)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return definition_can_write(self.coordinator.data, self.entity_key)

    async def async_press(self) -> None:
        await self.runtime.commands.async_execute(self.entity_key, True)


def aqm_numbers(runtime: SihasRuntime) -> list[SihasControlNumber]:
    """AQM TVOC thresholds and R29 compensation, created when the first publication's definition attaches them."""
    def number(key: str, unit: str, capability, reading) -> SihasControlNumber:
        return SihasControlNumber(runtime, key, unit, supported=partial(definition_can_write, feature=key), capability=capability,
                                  reading=reading, write=partial(runtime.commands.async_execute, key))

    candidates = [
        *(number(key, UnitOfRatio.PARTS_PER_BILLION, partial(aqm_controls.tvoc_threshold_range, position=position),
                 partial(aqm_controls.tvoc_threshold, position=position))
          for position, key in enumerate(aqm_controls.TVOC_THRESHOLDS)),
        number("temperature_compensation", UnitOfTemperature.CELSIUS, lambda state: aqm_controls.TEMPERATURE_COMPENSATION_RANGE,
               aqm_controls.temperature_compensation),
        number("humidity_compensation", PERCENTAGE, lambda state: aqm_controls.HUMIDITY_COMPENSATION_RANGE,
               aqm_controls.humidity_compensation),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


def aqm_selects(runtime: SihasRuntime) -> list[SihasControlSelect]:
    """AQM R22 backlight and LCD R24 primary display, created when the first publication's definition attaches them."""
    def select(key: str, options, reading) -> SihasControlSelect:
        return SihasControlSelect(runtime, key, list(options), supported=partial(definition_can_write, feature=key),
                                  reading=lambda state: aqm_controls.current_option(options, reading(state.settings)),
                                  write=partial(runtime.commands.async_execute, key))

    candidates = [
        select("backlight", aqm_controls.BACKLIGHT_OPTIONS, lambda settings: settings.backlight),
        select("lcd_primary_display", aqm_controls.LCD_PRIMARY_OPTIONS, lambda settings: settings.display.primary),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


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


def aqm_link_switches(runtime: SihasRuntime) -> list[SihasControlSwitch]:
    """Ten toggle-only link rules: R62 read state; writes select, verify and toggle one existing rule."""
    def reading(rule: int):
        return lambda state: (aqm_link_toggle.enabled(state.selected_link, rule), {})

    def supported(key: str, rule: int):
        def check(snapshot: DeviceSnapshot) -> bool:
            return definition_can_write(snapshot, key) and aqm_link_toggle.enabled(snapshot.state.selected_link, rule) is not None
        return check

    candidates = [
        SihasControlSwitch(runtime, "link_rule", index=rule, supported=supported(f"link_rule_{rule}", rule), reading=reading(rule),
                           write=partial(runtime.commands.async_execute, f"link_rule_{rule}"))
        for rule in range(aqm_link_toggle.RULES)
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


def _prepare(config: int, firmware: str | None) -> DeviceBinding:
    prepared = aqm_definition.prepare(config=config, firmware=firmware)
    return DeviceBinding(partial(aqm_definition.resolve, prepared=prepared), prepared)


FAMILY = FamilyRegistration(
    prepare=_prepare,
    poll_interval=timedelta(seconds=10),
    diagnostics=decode_diagnostics,
    sensitive=SENSITIVE_FIELDS,
    entities={
        Platform.BUTTON: lambda runtime: [AqmAction(runtime, key) for key in ACTION_INTENTS
                                          if definition_can_write(runtime.coordinator.data, key)],
        Platform.NUMBER: aqm_numbers,
        Platform.SELECT: aqm_selects,
        Platform.SENSOR: lambda runtime: Aqm300(runtime).get_sub_entities(),
        Platform.SWITCH: aqm_link_switches,
    },
)
