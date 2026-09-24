from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from typing_extensions import Final

from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
    ICON_POWER_SOCKET,
)
from .devices.hvm import controls as hvm_controls
from .devices.hvm import schedule as hvm_schedule
from .entity import SihasEntity, SihasProjection

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "CCM":
        async_add_entities([Ccm300(runtime)])
    elif runtime.device.device_type == "BCM":
        async_add_entities([BcmScheduleSwitch(runtime)])
    elif runtime.device.device_type == "HVM" and runtime.coordinator.data.state.controls_qualified:
        async_add_entities(hvm_schedule_switches(runtime))


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


class HvmScheduleSwitch(SihasProjection, SwitchEntity):
    """One HVM stored schedule entry: the switch is only its stored enable flag.

    Every other decoded field is a read-only attribute; the manufacturer app
    remains the editor for them. Disabled by default at first Entity Registry
    creation, available only in the qualified control context, and always
    projecting refreshed readback.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    diagnostic_generated_attributes = frozenset({
        "kind", "month", "day", "weekdays", "repeat", "hour", "minute", "mode", "preserve_value", "temperature", "time_minutes",
        "start_hour", "end_hour", "period_hours", "on_minutes", "active_temperature", "end_action",
    })

    def __init__(self, runtime: SihasRuntime, key: str, translation_key: str, index: int, command, project) -> None:
        super().__init__(runtime, entity_key=f"{key}_{index}", translation_key=translation_key,
                         translation_placeholders={"number": str(index + 1)})
        self._command = command
        self._project = project

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.state.controls_qualified

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_enable(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_enable(False)

    async def _async_enable(self, enabled: bool) -> None:
        try:
            await self.runtime.commands.async_snapshot_write(partial(self._command, enabled=enabled))
        except ValueError as err:
            # The family selector rejects before any device I/O.
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        self._attr_is_on, self._attr_extra_state_attributes = self._project(self.coordinator.data.state)


def hvm_schedule_switches(runtime: SihasRuntime) -> list[HvmScheduleSwitch]:
    """Ten general slots (R30/R31..R48/R49) and two periodic banks (R50/R51, R28/R29)."""
    state = runtime.coordinator.data.state
    return [
        *(HvmScheduleSwitch(runtime, "general_schedule", "general_schedule", slot,
                            partial(hvm_controls.general_slot_command, slot=slot),
                            partial(_general_slot, slot=slot)) for slot in range(len(state.schedule_slots))),
        *(HvmScheduleSwitch(runtime, "periodic_schedule", "periodic_schedule", bank,
                            partial(hvm_controls.periodic_bank_command, bank=bank),
                            partial(_periodic_bank, bank=bank)) for bank in range(len(state.periodic_banks))),
    ]


def _general_slot(state, slot: int) -> tuple[bool | None, dict[str, Any]]:
    """Stored enable flag plus stable decoded fields; an undecodable slot exposes none."""
    item = state.schedule_slots[slot]
    time, setting = item.time, item.setting
    if time is None or setting is None:
        return None, {}
    result: dict[str, Any] = {"kind": time.kind}
    if time.kind == "date":
        result.update(month=time.month, day=time.day)
    else:
        result["weekdays"] = list(hvm_schedule.weekday_names(time.weekdays))
    result.update(repeat=time.repeat, hour=time.hour, minute=time.minute, mode=setting.mode, preserve_value=setting.preserve_value)
    if setting.temperature_celsius is not None:
        result["temperature"] = setting.temperature_celsius
    if setting.time_minutes is not None:
        result["time_minutes"] = setting.time_minutes
    return time.enabled, result


def _periodic_bank(state, bank: int) -> tuple[bool | None, dict[str, Any]]:
    """Stored enable flag plus decoded periodic fields; an undecodable bank exposes none."""
    fields = state.periodic_banks[bank].fields
    if fields is None:
        return None, {}
    return fields.enabled, {
        "weekdays": list(hvm_schedule.weekday_names(fields.weekdays)), "start_hour": fields.start_hour, "end_hour": fields.end_hour,
        "period_hours": fields.period_hours, "on_minutes": fields.on_minutes, "active_temperature": fields.active_temperature,
        "end_action": fields.end_action,
    }
