"""Synchronous datagram transport with request-scoped socket ownership."""

import logging
import socket
from typing import Protocol

from .const import BUF_SIZE, DEFAULT_TIMEOUT, PORT
from .identification import IpConv
from ..trace import ExchangeTrace

_LOGGER = logging.getLogger(__name__)


class DatagramTransport(Protocol):
    """Production composition boundary for one device's raw request/response I/O.

    Implementations own retries and release request resources before returning or
    raising. TimeoutError and OSError retain their normal communication meanings.
    Packet validity and register meaning belong to the caller's protocol layer.
    This is a synchronous boundary; async consumers must use an executor.
    """

    def exchange(self, data: bytes, *, retry: int = 1, trace: ExchangeTrace | None = None) -> bytes:
        """Return one response, retrying only receive timeouts up to retry attempts."""
        ...


class UdpTransport:
    """One UDP endpoint; no socket is retained between requests.

    Each exchange reuses its socket for the existing receive-timeout retries.
    The endpoint and timeout are explicit production connection settings. Default
    device traffic remains IPv4 UDP port 502 with a 0.5-second receive timeout.
    """

    def __init__(self, ip: str, port: int = PORT, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._address = (IpConv.remove_leading_zero(ip), port)
        self._timeout = timeout

    def exchange(self, data: bytes, *, retry: int = 1, trace: ExchangeTrace | None = None) -> bytes:
        """Return raw bytes, or raise after closing the request's socket.

        retry is the total attempt count, not an additional retry count. There is
        no backoff or protocol-error retry. A cancelled executor await does not
        interrupt this synchronous operation; its normal timeout/finally cleanup
        still runs, and no socket is owned by the awaiting coroutine.
        """
        attempt, stage, outcome = 0, "socket", "error"
        if trace is not None:
            trace.record(0, "exchange_started")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                for attempt in range(1, retry + 1):
                    stage = "send"
                    if trace is not None:
                        trace.record(attempt, "send_attempt", payload=data)
                    try:
                        sock.sendto(data, self._address)
                        if trace is not None:
                            trace.record(attempt, "sent")
                        if _LOGGER.isEnabledFor(logging.DEBUG):
                            _LOGGER.debug("UDP TX endpoint=%s:%s data=%s", *self._address, data.hex())
                        stage = "receive_setup"
                        sock.settimeout(self._timeout)
                        stage = "receive"
                        response = sock.recv(BUF_SIZE)
                        if trace is not None:
                            trace.record(attempt, "received", payload=response)
                        if _LOGGER.isEnabledFor(logging.DEBUG):
                            _LOGGER.debug("UDP RX endpoint=%s:%s data=%s", *self._address, response.hex())
                        outcome = "success"
                        stage = "close"
                        return response
                    except socket.timeout:
                        if trace is not None:
                            trace.record(attempt, "timeout", error=stage)
                        continue
                stage = "close"
            stage = "attempts_exhausted"
            raise socket.timeout
        except Exception:
            outcome = "error"
            if trace is not None:
                # Stage-only descriptions cannot expose endpoint/exception contents.
                trace.record(attempt, "error", error=stage)
            raise
        finally:
            if trace is not None:
                trace.finish(attempt, outcome)
