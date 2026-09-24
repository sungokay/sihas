"""Platform for climate integration."""

from __future__ import annotations

from functools import partial
import logging
from typing import List, cast, Final

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACAction,
    HVACMode,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    ClimateEntityFeature,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    ICON_COOLER,
    ICON_HEATER,
)
from .devices import tcm
from .devices.hvm import controls as hvm_controls
from .entity import SihasEntity, SihasEntityGroup, SihasProjection

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES: Final = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    family = runtime.device.device_type
    if family == "HCM":
        async_add_entities(Hcm300(runtime).get_sub_entities())
    elif family == "HVM":
        async_add_entities(Hvm300(runtime).get_sub_entities())
    elif family == "HQM":
        async_add_entities(Hqm300(runtime).get_sub_entities())
    elif family == "ACM":
        async_add_entities([Acm300(runtime)])
    elif family == "BCM":
        async_add_entities([Bcm300(runtime)])
    elif family == "TCM":
        async_add_entities([Tcm300(runtime)])


ROOM_SUPPORTED_FEATURES: Final = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
)


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
        await self.runtime.commands.async_room_power(self._number_of_room, hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_room_temperature(self._number_of_room, cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self):
        state = self.room_state
        # Preserve the existing presentation limit, including the whole-degree case.
        self._attr_max_temp = 65 if state.temperature_step == 0 else (65 / 2)
        self._attr_target_temperature_step = state.temperature_step
        self._attr_hvac_mode = HVACMode.HEAT if state.powered else HVACMode.OFF
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature
        self._attr_hvac_action = HVACAction.HEATING if state.valve_open else HVACAction.IDLE


class Hvm300(SihasEntityGroup):
    def get_sub_entities(self) -> List[Entity]:
        return [HvmVirtualThermostat(self, i) for i in range(len(self.runtime.coordinator.data.state))]


class HvmVirtualThermostat(SihasProjection, ClimateEntity):
    _attr_icon = ICON_HEATER
    _attr_hvac_modes: Final = [HVACMode.OFF, HVACMode.HEAT]
    _attr_max_temp = 65
    _attr_min_temp: Final = 0
    _attr_supported_features = ROOM_SUPPORTED_FEATURES
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS
    diagnostic_generated_attributes = frozenset({"preset_mode", "preset_modes"})

    def __init__(self, group: Hvm300, number_of_room: int) -> None:
        super().__init__(group.runtime, entity_key=f"room_{number_of_room}", translation_key="room",
                         translation_placeholders={"number": str(number_of_room + 1)})
        self._number_of_room = number_of_room

    @property
    def room_state(self):
        return self.coordinator.data.state[self._number_of_room]

    async def async_set_hvac_mode(self, hvac_mode: str):
        await self.runtime.commands.async_room_power(self._number_of_room, hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_room_temperature(self._number_of_room, cast(float, kwargs.get(ATTR_TEMPERATURE)))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.runtime.commands.async_snapshot_write(partial(hvm_controls.preset_command, preset=preset_mode))

    @property
    def available(self) -> bool:
        return super().available and self._number_of_room < len(self.coordinator.data.state)

    def _project_state(self):
        snapshot = self.coordinator.data
        # A successful zero-room snapshot has no summary for an existing entity.
        # Keep it unavailable without retaining a previously qualified limit pair.
        if self._number_of_room < len(snapshot.state):
            state = self.room_state
            # Preserve the existing presentation limit, including the whole-degree case.
            self._attr_max_temp = 65 if state.temperature_step == 0 else (65 / 2)
            self._attr_target_temperature_step = state.temperature_step
            self._attr_hvac_mode = HVACMode.HEAT if state.powered else HVACMode.OFF
            self._attr_current_temperature = state.current_temperature
            self._attr_target_temperature = state.target_temperature
            self._attr_hvac_action = HVACAction.HEATING if state.valve_open else HVACAction.IDLE
        self._attr_min_temp = 0
        self._attr_max_temp = 65 if self._attr_target_temperature_step == 0 else (65 / 2)
        if self._number_of_room == 0 and (limits := snapshot.state.climate_limits) is not None:
            self._attr_min_temp, self._attr_max_temp = limits
        # R2 preset is independent of R0 power and offered only in the qualified single-room context.
        presets = self._number_of_room == 0 and snapshot.state.controls_qualified
        self._attr_supported_features = ROOM_SUPPORTED_FEATURES | ClimateEntityFeature.PRESET_MODE if presets else ROOM_SUPPORTED_FEATURES
        self._attr_preset_modes = list(hvm_controls.PRESETS) if presets else None
        self._attr_preset_mode = snapshot.state.observation.selected_mode if presets else None


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
        await self.runtime.commands.async_room_power(self._number_of_room, hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_room_temperature(self._number_of_room, cast(float, kwargs.get(ATTR_TEMPERATURE)))

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
        await self.runtime.commands.async_hqm_power(hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_hqm_temperature(cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self):
        state = self.coordinator.data.state.standalone
        self._attr_hvac_mode = HVACMode.HEAT if state.powered else HVACMode.OFF
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature
        if state.action is None:
            _LOGGER.warning("Not implemented HVAC actions (%s, %s)", state.raw_power, state.raw_valve)
        else:
            self._attr_hvac_action = HVACAction(state.action)


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
        await self.runtime.commands.async_acm_mode(hvac_mode)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_acm_temperature(cast(float, kwargs.get(ATTR_TEMPERATURE)))

    async def async_set_swing_mode(self, swing_mode):
        await self.runtime.commands.async_acm_swing(swing_mode)

    async def async_set_fan_mode(self, fan_mode):
        await self.runtime.commands.async_acm_fan(fan_mode)

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_hvac_mode = HVACMode(state.mode)
        self._attr_swing_mode = state.swing
        self._attr_fan_mode = state.fan
        if state.current_temperature is not None:
            self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature


# BCM

BCM_SUPPORTED_FEATURES: Final = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
)


class Bcm300(SihasEntity, ClimateEntity):
    _attr_icon = ICON_HEATER
    _attr_hvac_modes: Final = [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    ]
    _attr_max_temp: Final = 80
    _attr_min_temp: Final = 0
    _attr_supported_features: Final = BCM_SUPPORTED_FEATURES
    _attr_target_temperature_step: Final = 1
    _attr_temperature_unit: Final = UnitOfTemperature.CELSIUS

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='climate')

    async def async_set_hvac_mode(self, hvac_mode: str):
        mode = {HVACMode.AUTO: "temperature", HVACMode.HEAT: "schedule", HVACMode.FAN_ONLY: "away", HVACMode.OFF: "off"}.get(hvac_mode)
        if mode is not None:
            await self.runtime.commands.async_bcm_mode(mode)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_bcm_temperature(cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_hvac_mode = {
            "off": HVACMode.OFF, "schedule": HVACMode.HEAT,
            "away": HVACMode.FAN_ONLY, "temperature": HVACMode.AUTO,
        }[state.mode]
        self._attr_hvac_action = HVACAction(state.action)
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature


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
        await self.runtime.commands.async_tcm_mode(hvac_mode)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_tcm_temperature(cast(float, kwargs.get(ATTR_TEMPERATURE)))

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_hvac_mode = HVACMode.OFF if not state.powered else (
            HVACMode.HEAT if state.mode == tcm.RunMode.HEATING else HVACMode.COOL
        )
        self._attr_current_temperature = state.current_temperature
        self._attr_target_temperature = state.target_temperature
