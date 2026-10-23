"""Shared full-device refresh and HA communication availability."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import SihasClient
from .devices.definition import DefinitionResolver
from .devices.state import DeviceSnapshot
from .errors import ModbusNotEnabledError, PacketSizeError

_LOGGER = logging.getLogger(__name__)

# Consecutive failed logical polls (each already using the client retry budget)
# after which shared communication availability becomes false.
POLL_FAILURE_THRESHOLD = 2


class SihasCoordinator(DataUpdateCoordinator[DeviceSnapshot]):
    """Publish one complete decoded snapshot per logical client poll.

    The client owns executor I/O and existing transport retries. Device callables
    own all decoding. HA owns refresh scheduling, update success, listener
    notification, initial-refresh failure and ConfigEntry shutdown.

    Every refresh still polls the device. A successful refresh whose snapshot equals
    the previous one (raw registers included) does not notify listeners again;
    update-success changes always notify.

    Communication availability is owned here, separately from update success.
    A transient communication failure (`OSError`, including timeouts, or
    `PacketSizeError`) keeps the last publication available until
    `POLL_FAILURE_THRESHOLD` consecutive logical polls have failed. Any other
    refresh failure ends availability immediately. The failed refresh itself is
    still reported as an unsuccessful update. Command outcomes never change it;
    only the result of an actual poll does. A refresh without a previous
    successful publication is never available.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry | None,
        client: SihasClient,
        resolver: DefinitionResolver,
        update_interval: timedelta,
        *,
        first_refresh_retry: int = 3,
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"sihas {entry.unique_id}" if entry else "sihas validation", update_interval=update_interval,
            always_update=False,
        )
        self.client = client
        self._resolver = resolver
        # Preserve the legacy HCM/HVM topology read's single attempt. Subsequent
        # shared refreshes retain the established three-attempt client contract.
        self._next_poll_retry = first_refresh_retry
        self._consecutive_poll_failures = 0
        self._transient_poll_failure = False
        self._previous_update_success = True

    @property
    def communication_available(self) -> bool:
        """Whether the retained publication still represents a communicating device."""
        return self.data is not None and self._consecutive_poll_failures < POLL_FAILURE_THRESHOLD

    async def _async_update_data(self) -> DeviceSnapshot:
        retry, self._next_poll_retry = self._next_poll_retry, 3
        self._transient_poll_failure = False
        self._previous_update_success = self.last_update_success
        try:
            registers = tuple(await self.client.async_poll(retry=retry))
            definition = self._resolver(registers)
            state = definition.decode(registers)
        except (OSError, PacketSizeError) as err:
            self._transient_poll_failure = True
            raise UpdateFailed(f"Cannot refresh SiHAS device: {err}") from err
        except (ModbusNotEnabledError, IndexError, KeyError, ValueError) as err:
            raise UpdateFailed(f"Cannot refresh SiHAS device: {err}") from err
        _LOGGER.debug("Poll snapshot coordinator=%s registers=%s", self.name, registers)
        return DeviceSnapshot(registers, state, definition)

    @callback
    def _async_refresh_finished(self) -> None:
        """Account the finished poll and publish an availability-only transition.

        HA notifies listeners whenever update success changes, but not between two
        failed refreshes, so reaching the threshold there is published here.
        """
        was_available = self.communication_available
        if self.last_update_success:
            self._consecutive_poll_failures = 0
        elif self._transient_poll_failure:
            self._consecutive_poll_failures = min(self._consecutive_poll_failures + 1, POLL_FAILURE_THRESHOLD)
        else:
            self._consecutive_poll_failures = POLL_FAILURE_THRESHOLD
        if not self._previous_update_success and not self.last_update_success and was_available != self.communication_available:
            self.async_update_listeners()
