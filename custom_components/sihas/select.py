"""Platform for select integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.bcm import controls as bcm_controls
from .devices.bcm import state as bcm
from .devices.hvm import controls as hvm_controls
from .devices.state import DeviceSnapshot
from .entity import SihasProjection, definition_can_write
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "BCM":
        async_add_entities(bcm_selects(runtime))
    elif runtime.device.device_type == "HVM" and runtime.coordinator.data.state.controls_qualified:
        async_add_entities(hvm_selects(runtime))


class SihasControlSelect(SihasProjection, SelectEntity):
    """Device control select shared by device families.

    Available only while `supported` holds for the current publication. The
    selected option and attributes are always the refreshed readback; an unknown
    code has no option. The family selector rejects invalid requests before I/O.
    Entity category and the Entity Registry creation default follow the shared
    control policy; HA keeps a user's later enable/disable choice.
    """

    def __init__(self, runtime: SihasRuntime, key: str, options: list[str], *,
                 supported: Callable[[DeviceSnapshot], bool], reading: Callable[[Any], str | None],
                 write: Callable[[str], Awaitable[None]], attributes: Callable[[Any], dict[str, Any]] | None = None,
                 category: EntityCategory | None = EntityCategory.CONFIG, enabled_default: bool = False) -> None:
        super().__init__(runtime, entity_key=key, translation_key=key)
        self._attr_options = options
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled_default
        self._supported = supported
        self._reading = reading
        self._write = write
        self._attribute_reading = attributes
        self.diagnostic_generated_attributes = frozenset({"options"})

    @property
    def available(self) -> bool:
        return super().available and self._supported(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        try:
            await self._write(option)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_current_option = self._reading(state)
        if self._attribute_reading is not None:
            self._attr_extra_state_attributes = self._attribute_reading(state)
            self.diagnostic_generated_attributes = frozenset({"options", *self._attr_extra_state_attributes})


def hvm_selects(runtime: SihasRuntime) -> list[SihasControlSelect]:
    """R6 display and R7 backlight in the qualified single-room context."""
    def qualified(snapshot: DeviceSnapshot) -> bool:
        return snapshot.state.controls_qualified

    def select(key: str, options: dict[str, int], command, reading) -> SihasControlSelect:
        return SihasControlSelect(
            runtime, key, list(options), supported=qualified, reading=lambda state: reading(state.observation.settings).value,
            write=lambda option: runtime.commands.async_snapshot_write(partial(command, option=option)),
        )

    return [
        select("display", hvm_controls.DISPLAY_OPTIONS, hvm_controls.display_command, lambda settings: settings.display),
        select("backlight", hvm_controls.BACKLIGHT_OPTIONS, hvm_controls.backlight_command, lambda settings: settings.backlight),
    ]


def bcm_selects(runtime: SihasRuntime) -> list[SihasControlSelect]:
    """Controller-qualified BCM selects, created when the first publication's definition attaches their writers."""
    def select(key: str, options: list[str], reading, **kwargs) -> SihasControlSelect:
        return SihasControlSelect(runtime, key, options, supported=partial(definition_can_write, feature=key), reading=reading,
                                  write=partial(runtime.commands.async_execute, key), **kwargs)

    candidates = [
        select("operating_program", list(bcm.PROGRAMS), lambda state: state.program,
               attributes=bcm_controls.program_attributes, category=None, enabled_default=True),
        select("heating_level", list(bcm_controls.HEATING_LEVELS), lambda state: state.heating_level.value,
               category=None, enabled_default=True),
        select("backlight", list(bcm_controls.BACKLIGHT_OPTIONS),
               lambda state: bcm_controls.current_option(bcm_controls.BACKLIGHT_OPTIONS, state.settings.backlight.mode)),
        select("touch_lock", list(bcm_controls.TOUCH_LOCK_OPTIONS),
               lambda state: bcm_controls.current_option(bcm_controls.TOUCH_LOCK_OPTIONS, state.settings.touch_lock.mode)),
    ]
    return [entity for entity in candidates if definition_can_write(runtime.coordinator.data, entity.entity_key)]
