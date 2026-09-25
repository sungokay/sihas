from __future__ import annotations

from collections.abc import Awaitable, Callable
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
from .devices.bcm import controls as bcm_controls
from .devices.bcm import settings as bcm_settings
from .devices.controls import StoredToggle, toggle_offered, weekday_names
from .devices.hvm import controls as hvm_controls
from .devices.hvm import schedule as hvm_schedule
from .devices.state import DeviceSnapshot
from .entity import SihasEntity, SihasProjection, definition_can_write

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "CCM":
        async_add_entities([Ccm300(runtime)])
    elif runtime.device.device_type == "BCM":
        async_add_entities(bcm_switches(runtime))
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


class SihasControlSwitch(SihasProjection, SwitchEntity):
    """Device control switch shared by device families.

    For a stored manufacturer-owned entry the switch is only its enable bit:
    the raw word is sufficient for state and write, and decoded fields are
    optional read-only attributes that are omitted when they do not decode. The
    manufacturer app remains the editor for every other field. Available only
    while `supported` holds for the current publication, always projecting
    refreshed readback. Config category and default-disabled Entity Registry
    creation follow the shared policy; HA keeps a user's later choice.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    diagnostic_generated_attributes = frozenset({
        "kind", "month", "day", "weekdays", "repeat", "hour", "minute", "mode", "preserve_value", "temperature", "time_minutes",
        "start_hour", "end_hour", "period_hours", "on_minutes", "active_temperature", "end_action",
        "timer_period_hours", "timer_run_minutes", "hot_water_level", "run_minutes", "temperature_control",
    })

    def __init__(self, runtime: SihasRuntime, key: str, *, supported: Callable[[DeviceSnapshot], bool],
                 reading: Callable[[Any], tuple[bool | None, dict[str, Any]]], write: Callable[[bool], Awaitable[None]],
                 index: int | None = None) -> None:
        super().__init__(runtime, entity_key=key if index is None else f"{key}_{index}", translation_key=key,
                         translation_placeholders=None if index is None else {"number": str(index + 1)})
        self._supported = supported
        self._reading = reading
        self._write = write

    @property
    def available(self) -> bool:
        return super().available and self._supported(self.coordinator.data)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_enable(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_enable(False)

    async def _async_enable(self, enabled: bool) -> None:
        try:
            await self._write(enabled)
        except ValueError as err:
            # The family selector rejects before any device I/O.
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        self._attr_is_on, self._attr_extra_state_attributes = self._reading(self.coordinator.data.state)


def _toggle_reading(toggle: StoredToggle | None, attributes: Callable[[], dict[str, Any]]) -> tuple[bool | None, dict[str, Any]]:
    return (toggle.enabled, attributes()) if toggle_offered(toggle) else (None, {})


def hvm_schedule_switches(runtime: SihasRuntime) -> list[SihasControlSwitch]:
    """Ten general slots (R30/R31..R48/R49) and two periodic banks (R50/R51, R28/R29)."""
    state = runtime.coordinator.data.state

    def switch(key: str, index: int, toggle, command, attributes) -> SihasControlSwitch:
        return SihasControlSwitch(
            runtime, key, index=index,
            supported=lambda snapshot: snapshot.state.controls_qualified and toggle_offered(toggle(snapshot.state)),
            reading=lambda current: _toggle_reading(toggle(current), lambda: attributes(current)),
            write=lambda enabled: runtime.commands.async_snapshot_write(partial(command, enabled=enabled)),
        )

    return [
        *(switch("general_schedule", slot, lambda current, slot=slot: hvm_schedule.slot_toggle(slot, current.schedule_slots[slot]),
                 partial(hvm_controls.general_slot_command, slot=slot), partial(_general_slot, slot=slot))
          for slot in range(len(state.schedule_slots))),
        *(switch("periodic_schedule", bank, lambda current, bank=bank: hvm_schedule.periodic_toggle(bank, current.periodic_banks[bank]),
                 partial(hvm_controls.periodic_bank_command, bank=bank), partial(_periodic_bank, bank=bank))
          for bank in range(len(state.periodic_banks))),
    ]


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


def bcm_switches(runtime: SihasRuntime) -> list[SihasControlSwitch]:
    """Controller-qualified R62 buzzer, general schedule slots and interval-repeat enable."""
    def supported(key: str, toggle=None):
        def check(snapshot: DeviceSnapshot) -> bool:
            return definition_can_write(snapshot, key) and (toggle is None or toggle_offered(toggle(snapshot.state)))
        return check

    def buzzer(state) -> tuple[bool | None, dict[str, Any]]:
        mode = state.settings.buzzer.mode
        return (None if mode is None else mode is bcm_settings.Buzzer.ENABLED), {}

    candidates = [
        SihasControlSwitch(runtime, "buzzer", supported=supported("buzzer"), reading=buzzer,
                           write=partial(runtime.commands.async_execute, "buzzer")),
        *(SihasControlSwitch(
            runtime, "general_schedule", index=slot,
            supported=supported(f"general_schedule_{slot}", partial(bcm_controls.general_toggle, slot=slot)),
            reading=lambda state, slot=slot: _toggle_reading(bcm_controls.general_toggle(state, slot),
                                                             lambda: bcm_controls.general_slot_attributes(state, slot)),
            write=partial(runtime.commands.async_execute, f"general_schedule_{slot}"),
        ) for slot in range(10)),
        SihasControlSwitch(runtime, "interval_repeat", supported=supported("interval_repeat", bcm_controls.interval_toggle),
                           reading=lambda state: _toggle_reading(bcm_controls.interval_toggle(state),
                                                                 lambda: bcm_controls.interval_attributes(state)),
                           write=partial(runtime.commands.async_execute, "interval_repeat")),
    ]
    snapshot = runtime.coordinator.data
    return [entity for entity in candidates if definition_can_write(snapshot, entity.entity_key)]
