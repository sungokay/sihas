"""Async-safe protocol client for the ConfigEntry runtime's communication boundary."""

from functools import partial

from homeassistant.core import HomeAssistant

from .protocol.packet import packet_builder
from .protocol.transport import DatagramTransport
from .trace import ExchangeTrace


class SihasClient:
    """Compose the authoritative codec with a device's synchronous transport.

    Runtime composition supplies DatagramTransport (normally UdpTransport).
    Network I/O, socket cleanup and all timeout retries run in HA's executor.
    Only small packet encode/decode operations run on the event loop.

    TimeoutError/OSError represent communication failures. PacketSizeError and
    ModbusNotEnabledError retain the existing protocol outcomes. The client does
    not translate those into HA availability or setup policy.

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
        """Write one existing register; preserve the existing acknowledgement checks."""
        response = await self._hass.async_add_executor_job(
            partial(self._transport.exchange, packet_builder.command(index, value), retry=retry)
        )
        packet_builder.validate_response(response)
