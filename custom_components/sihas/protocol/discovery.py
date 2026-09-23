"""Textual UDP discovery, separate from the register transport and protocol.

Async consumers execute DiscoveryTransport.scan in HA's executor. Each attempt
owns its socket; no resource or retry task is retained by the transport instance.
"""

import logging
import socket
from typing import Protocol

from .const import BUF_SIZE, PORT

_LOGGER = logging.getLogger(__name__)


class DiscoveryTransport(Protocol):
    """Synchronous textual scan exchange; each call owns all socket resources."""

    def scan(self, data: bytes, ip: str, *, attempts: int = 10) -> str | None:
        """Return scan text or None on exhausted timeouts; decode/transport errors propagate."""
        ...


class UdpDiscoveryTransport:
    """Keep the existing ten attempts, two-second timeout and per-attempt socket."""

    def __init__(self, port: int = PORT, timeout: float = 2) -> None:
        self.port = port
        self.timeout = timeout

    def scan(self, data: bytes, ip: str, *, attempts: int = 10) -> str | None:
        retry = attempts
        while retry:
            try:
                _LOGGER.debug("Textual discovery attempt")
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(data, (ip, self.port))
                    sock.settimeout(self.timeout)
                    return sock.recv(BUF_SIZE).decode()
            except socket.timeout:
                retry -= 1
        _LOGGER.debug("Textual discovery exhausted receive timeouts")
        return None
