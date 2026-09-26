"""Async-safe protocol client for the ConfigEntry runtime's communication boundary."""

from functools import partial
import logging
from typing import Final

from homeassistant.core import HomeAssistant

from .errors import ResponsePidMismatchError
from .protocol.packet import packet_builder
from .protocol.transport import DatagramTransport
from .trace import ExchangeTrace

_LOGGER = logging.getLogger(__name__)

# Command-level attempts when an acknowledgement does not echo the request PID.
COMMAND_PID_ATTEMPTS: Final = 3


class SihasClient:
    """Compose the authoritative codec with a device's synchronous transport.

    Runtime composition supplies DatagramTransport (normally UdpTransport).
    Network I/O, socket cleanup and all timeout retries run in HA's executor.
    Only small packet encode/decode operations run on the event loop.

    TimeoutError/OSError represent communication failures. PacketSizeError and
    ModbusNotEnabledError retain the existing protocol outcomes; exhausted command
    PID attempts raise ResponsePidMismatchError. The client does not translate
    those into HA availability or setup policy. Polls do not require PID equality.

    Resources are scoped to each transport exchange, so there is no persistent
    socket or close operation on this client. Cancelling an await leaves the
    bounded executor operation responsible for finishing and releasing its socket.
    """

    def __init__(self, hass: HomeAssistant, transport: DatagramTransport) -> None:
        self._hass = hass
        self._transport = transport

    async def async_poll(self, *, retry: int = 3, trace: ExchangeTrace | None = None) -> list[int]:
        """Read the existing unsigned 64-register snapshot without device decoding."""
        response = await self._hass.async_add_executor_job(
            partial(self._transport.exchange, packet_builder.poll(), retry=retry, **({"trace": trace} if trace is not None else {}))
        )
        return packet_builder.extract_registers(response)

    async def async_command(self, index: int, value: int, *, retry: int = 3) -> None:
        """Write one existing register; the acknowledgement must echo the request PID.

        Each PID attempt builds a fresh packet, so it has a new PID; the transport's
        `retry` timeout attempts resend that same packet. A response with another PID
        starts the next PID attempt, up to COMMAND_PID_ATTEMPTS. A matching PID gets
        the existing acknowledgement checks; transport and protocol failures are not
        retried here.
        """
        for _ in range(COMMAND_PID_ATTEMPTS):
            request = packet_builder.command(index, value)
            response = await self._hass.async_add_executor_job(partial(self._transport.exchange, request, retry=retry))
            expected, received = packet_builder.packet_pid(request), packet_builder.packet_pid(response)
            if received == expected:
                packet_builder.validate_response(response)
                return
            _LOGGER.debug("Command acknowledgement PID mismatch: expected=%s received=%s", expected, received)
        raise ResponsePidMismatchError(COMMAND_PID_ATTEMPTS)
