"""Shared full-device refresh and HA communication availability."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import SihasClient
from .devices.definition import DefinitionResolver
from .devices.state import DeviceSnapshot, StateDecoder
from .errors import ModbusNotEnabledError, PacketSizeError

_LOGGER = logging.getLogger(__name__)


class SihasCoordinator(DataUpdateCoordinator[DeviceSnapshot]):
    """Publish one complete decoded snapshot per logical client poll.

    The client owns executor I/O and existing transport retries. Device callables
    own all decoding. HA owns refresh scheduling, update success, listener
    notification, initial-refresh failure and ConfigEntry shutdown.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry | None,
        client: SihasClient,
        decoder: StateDecoder,
        update_interval: timedelta,
        *,
        first_refresh_retry: int = 3,
        definition_resolver: DefinitionResolver | None = None,
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"sihas {entry.unique_id}" if entry else "sihas validation", update_interval=update_interval,
        )
        self.client = client
        self._decoder = decoder
        self._definition_resolver = definition_resolver
        # Preserve the legacy HCM/HVM topology read's single attempt. Subsequent
        # shared refreshes retain the established three-attempt client contract.
        self._next_poll_retry = first_refresh_retry

    async def _async_update_data(self) -> DeviceSnapshot:
        retry, self._next_poll_retry = self._next_poll_retry, 3
        try:
            registers = tuple(await self.client.async_poll(retry=retry))
            definition = self._definition_resolver(registers) if self._definition_resolver is not None else None
            state = definition.decode(registers) if definition is not None else self._decoder(registers)
        except (OSError, ModbusNotEnabledError, PacketSizeError, IndexError, KeyError, ValueError) as err:
            raise UpdateFailed(f"Cannot refresh SiHAS device: {err}") from err
        _LOGGER.debug("Poll snapshot coordinator=%s registers=%s", self.name, registers)
        return DeviceSnapshot(registers, state, definition)
