"""ACM remote buttons and explicitly qualified AQM one-shot projections."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES, ICON_BUTTON
from .entity import SihasProjection, definition_can_write
from .devices.aqm.actions import ACTION_INTENTS
from .runtime import SihasConfigEntry, SihasRuntime

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    if runtime.device.device_type == "ACM":
        async_add_entities([AcmUCR(runtime, index) for index in coordinator.data.state.remote_buttons])
    elif runtime.device.device_type == "AQM":
        async_add_entities([AqmAction(runtime, key) for key in ACTION_INTENTS if definition_can_write(coordinator.data, key)])


class AcmUCR(SihasProjection, ButtonEntity):
    _attr_icon = ICON_BUTTON

    def __init__(self, runtime: SihasRuntime, number_of_button: int):
        super().__init__(runtime, entity_key=f"ucr_{number_of_button}", translation_key="remote",
                         translation_placeholders={"number": str(number_of_button + 1)})
        self.number_of_button = number_of_button

    async def async_press(self) -> None:
        await self.runtime.commands.async_acm_remote(self.number_of_button)


class AqmAction(SihasProjection, ButtonEntity):
    """Stateless invocation; HA timestamps never imply device completion."""

    def __init__(self, runtime: SihasRuntime, feature_key: str):
        if feature_key not in ACTION_INTENTS:
            raise ValueError("Unknown AQM action button")
        super().__init__(runtime, entity_key=feature_key, translation_key=feature_key)
        if feature_key.startswith("log_reset_"):
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return definition_can_write(self.coordinator.data, self.entity_key)

    async def async_press(self) -> None:
        await self.runtime.commands.async_execute(self.entity_key, True)
