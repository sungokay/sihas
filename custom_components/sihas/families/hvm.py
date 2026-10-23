"""HVM Home Assistant presentation owner."""
from __future__ import annotations

from functools import partial
from typing import Any, cast, Final, List

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature, UnitOfTime
from homeassistant.helpers.entity import Entity

from .registration import FamilyRegistration
from ..climate import ROOM_SUPPORTED_FEATURES
from ..const import ICON_HEATER
from ..devices.controls import NumberRange, toggle_offered, weekday_names
from ..devices.hvm import controls as hvm_controls, definition as hvm_definition, observation as hvm_observation, schedule as hvm_schedule
from ..devices.hvm.diagnostics import decode_diagnostics
from ..devices.state import DeviceBinding
from ..entity import definition_can_write, SihasEntityGroup, SihasProjection
from ..number import SihasControlNumber
from ..runtime import SihasRuntime
from ..select import SihasControlSelect
from ..switch import toggle_reading, SihasControlSwitch


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
        await self.runtime.commands.async_execute(f"room_{self._number_of_room}_power", hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs):
        await self.runtime.commands.async_execute(f"room_{self._number_of_room}_target", cast(float, kwargs.get(ATTR_TEMPERATURE)))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.runtime.commands.async_execute("preset", preset_mode)

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
        presets = self._number_of_room == 0 and definition_can_write(snapshot, "preset")
        self._attr_supported_features = ROOM_SUPPORTED_FEATURES | ClimateEntityFeature.PRESET_MODE if presets else ROOM_SUPPORTED_FEATURES
        self._attr_preset_modes = list(hvm_controls.PRESETS) if presets else None
        self._attr_preset_mode = snapshot.state.observation.selected_mode if presets else None


def _celsius(temperature: hvm_observation.Temperature) -> float | None:
    return float(temperature.celsius) if temperature.celsius is not None else None


def hvm_numbers(runtime: SihasRuntime) -> list[SihasControlNumber]:
    """R8 compensation, R9 ON minutes, R11 away temperature, R14 deadband and R13/R12 limits."""
    def number(key: str, unit: str, capability, reading, *, enabled_default: bool) -> SihasControlNumber:
        return SihasControlNumber(
            runtime, key, unit, supported=partial(definition_can_write, feature=key),
            capability=lambda state: capability(state.observation), reading=lambda state: reading(state.observation),
            write=partial(runtime.commands.async_execute, key), enabled_default=enabled_default,
        )

    def fixed(capability: NumberRange):
        return lambda observed: capability

    celsius = UnitOfTemperature.CELSIUS
    candidates = [
        number("temperature_compensation", celsius, fixed(hvm_controls.COMPENSATION_RANGE),
               lambda observed: _celsius(observed.settings.compensation), enabled_default=False),
        number("on_minutes", UnitOfTime.MINUTES, fixed(hvm_controls.ON_MINUTES_RANGE),
               lambda observed: observed.detail.on_minutes.value, enabled_default=False),
        number("away_temperature", celsius, fixed(hvm_controls.AWAY_RANGE),
               lambda observed: _celsius(observed.settings.away), enabled_default=True),
        number("deadband", celsius, fixed(hvm_controls.DEADBAND_RANGE),
               lambda observed: _celsius(observed.settings.deadband), enabled_default=False),
        number("lower_temperature_limit", celsius, hvm_controls.lower_limit_range,
               lambda observed: observed.settings.limits.lower.value, enabled_default=False),
        number("upper_temperature_limit", celsius, hvm_controls.upper_limit_range,
               lambda observed: observed.settings.limits.upper.value, enabled_default=False),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


def hvm_selects(runtime: SihasRuntime) -> list[SihasControlSelect]:
    """R6 display and R7 backlight, created when the first publication's definition attaches them."""
    def select(key: str, options: dict[str, int], reading) -> SihasControlSelect:
        return SihasControlSelect(
            runtime, key, list(options),
            supported=partial(definition_can_write, feature=key),
            reading=lambda state: reading(state.observation.settings).value,
            write=partial(runtime.commands.async_execute, key),
        )

    candidates = [
        select("display", hvm_controls.DISPLAY_OPTIONS, lambda settings: settings.display),
        select("backlight", hvm_controls.BACKLIGHT_OPTIONS, lambda settings: settings.backlight),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


def hvm_schedule_switches(runtime: SihasRuntime) -> list[SihasControlSwitch]:
    """Ten general slots (R30/R31..R48/R49) and two periodic banks (R50/R51, R28/R29)."""
    state = runtime.coordinator.data.state

    def switch(key: str, index: int, toggle, attributes) -> SihasControlSwitch:
        feature = f"{key}_{index}"
        return SihasControlSwitch(
            runtime, key, index=index,
            supported=lambda snapshot: definition_can_write(snapshot, feature) and toggle_offered(toggle(snapshot.state)),
            reading=lambda current: toggle_reading(toggle(current), lambda: attributes(current)),
            write=partial(runtime.commands.async_execute, feature),
        )

    candidates = [
        *(switch("general_schedule", slot, lambda current, slot=slot: hvm_schedule.slot_toggle(slot, current.schedule_slots[slot]),
                 partial(_general_slot, slot=slot))
          for slot in range(len(state.schedule_slots))),
        *(switch("periodic_schedule", bank, lambda current, bank=bank: hvm_schedule.periodic_toggle(bank, current.periodic_banks[bank]),
                 partial(_periodic_bank, bank=bank))
          for bank in range(len(state.periodic_banks))),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]


def _general_slot(state, slot: int) -> dict[str, Any]:
    """Stable decoded fields; an undecodable slot exposes none."""
    item = state.schedule_slots[slot]
    time, setting = item.time, item.setting
    if time is None or setting is None:
        return {}
    result: dict[str, Any] = {"kind": time.kind}
    if time.kind == "date":
        result.update(month=time.month, day=time.day)
    else:
        result["weekdays"] = list(weekday_names(time.weekdays))
    result.update(repeat=time.repeat, hour=time.hour, minute=time.minute, mode=setting.mode, preserve_value=setting.preserve_value)
    if setting.temperature_celsius is not None:
        result["temperature"] = setting.temperature_celsius
    if setting.time_minutes is not None:
        result["time_minutes"] = setting.time_minutes
    return result


def _periodic_bank(state, bank: int) -> dict[str, Any]:
    """Decoded periodic fields; an undecodable bank exposes none."""
    fields = state.periodic_banks[bank].fields
    if fields is None:
        return {}
    return {
        "weekdays": list(weekday_names(fields.weekdays)), "start_hour": fields.start_hour, "end_hour": fields.end_hour,
        "period_hours": fields.period_hours, "on_minutes": fields.on_minutes, "active_temperature": fields.active_temperature,
        "end_action": fields.end_action,
    }


def _prepare(config: int, firmware: str | None) -> DeviceBinding:
    prepared = hvm_definition.prepare(firmware)
    return DeviceBinding(partial(hvm_definition.resolve, prepared=prepared), prepared)


FAMILY = FamilyRegistration(
    prepare=_prepare,
    # The initial topology read uses a single attempt; later polls use three.
    first_refresh_retry=1,
    diagnostics=decode_diagnostics,
    entities={
        Platform.CLIMATE: lambda runtime: Hvm300(runtime).get_sub_entities(),
        Platform.NUMBER: hvm_numbers,
        Platform.SELECT: hvm_selects,
        Platform.SWITCH: hvm_schedule_switches,
    },
)
