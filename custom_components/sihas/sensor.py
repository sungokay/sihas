from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PARALLEL_UPDATES
from .devices.state import DeviceState
from .entity import family_entities
from .runtime import SihasConfigEntry

PARALLEL_UPDATES = DEFAULT_PARALLEL_UPDATES


@dataclass(frozen=True, kw_only=True)
class SihasSensorEntityDescription(SensorEntityDescription):
    """`SensorEntityDescription` plus a projection from the device-owned state.

    `key` is always the stable `entity_key`; it carries no other meaning and
    must never be derived from `device_class`, unit, or any other metadata field here.
    """

    value_handler: Callable[[DeviceState], int | float]


async def async_setup_entry(
    hass: HomeAssistant, entry: SihasConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(family_entities(entry.runtime_data, Platform.SENSOR))
