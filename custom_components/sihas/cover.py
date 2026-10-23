"""Platform for cover integration."""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from typing_extensions import Final

from .const import DEFAULT_PARALLEL_UPDATES
from .entity import family_entities
from .runtime import SihasConfigEntry

PARALLEL_UPDATES: Final = DEFAULT_PARALLEL_UPDATES


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(family_entities(entry.runtime_data, Platform.COVER))
