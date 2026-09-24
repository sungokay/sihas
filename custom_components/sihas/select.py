"""Platform for select integration."""
from __future__ import annotations

from functools import partial

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from typing import Final

from homeassistant.components.select import SelectEntity

from .devices.bcm import state as bcm
from .devices.hvm import controls as hvm_controls
from .entity import SihasEntity, SihasProjection
from .runtime import SihasConfigEntry, SihasRuntime
from .const import (
    DEFAULT_PARALLEL_UPDATES,
)

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.device.device_type == "BCM":
        async_add_entities([BcmOccupancySelect(runtime)])
    elif runtime.device.device_type == "HVM" and runtime.coordinator.data.state.controls_qualified:
        async_add_entities(hvm_selects(runtime))


class BcmOccupancySelect(SihasEntity, SelectEntity):
    """BCM-300 occupancy select: home / away (reg[5])."""

    _attr_options: Final = [bcm.OCCUPANCY_HOME, bcm.OCCUPANCY_AWAY]

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='occupancy', translation_key='occupancy')

    async def async_select_option(self, option: str) -> None:
        await self.runtime.commands.async_bcm_occupancy(option)

    def _project_state(self) -> None:
        self._attr_current_option = bcm.OCCUPANCY_AWAY if self.coordinator.data.state.away else bcm.OCCUPANCY_HOME


class HvmSettingSelect(SihasProjection, SelectEntity):
    """Device-level HVM setting projected from the published observation.

    Available only while the current publication is in the qualified control
    context. The selected option is always the refreshed readback. Disabled by
    default at first Entity Registry creation; a user's later choice is kept.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    diagnostic_generated_attributes = frozenset({"options"})

    def __init__(self, runtime: SihasRuntime, key: str, options: dict[str, int], command, reading) -> None:
        super().__init__(runtime, entity_key=key, translation_key=key)
        self._attr_options = list(options)
        self._command = command
        self._reading = reading

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.state.controls_qualified

    async def async_select_option(self, option: str) -> None:
        await self.runtime.commands.async_snapshot_write(partial(self._command, option=option))

    def _project_state(self) -> None:
        self._attr_current_option = self._reading(self.coordinator.data.state.observation.settings).value


def hvm_selects(runtime: SihasRuntime) -> list[HvmSettingSelect]:
    """R6 display and R7 backlight; unknown codes project no option."""
    return [
        HvmSettingSelect(runtime, "display", hvm_controls.DISPLAY_OPTIONS, hvm_controls.display_command, lambda settings: settings.display),
        HvmSettingSelect(runtime, "backlight", hvm_controls.BACKLIGHT_OPTIONS, hvm_controls.backlight_command,
                         lambda settings: settings.backlight),
    ]
