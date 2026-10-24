"""Per-device operations, preserving the verified write/wait/refresh sequences."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
import logging
from typing import Any, TypeVar

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .client import SihasClient
from .const import DOMAIN
from .coordinator import SihasCoordinator
from .trace import ExchangeTrace
from .devices.definition import CommandExecution, CommandValue, CompletionPredicate
from .devices.state import DeviceSnapshot
from .protocol.multi_control import CommandMetadata, CommandPairs

_LOGGER = logging.getLogger(__name__)
_Result = TypeVar("_Result")
# Immediate read, then at most 500 ms of conditional waits; I/O retains its own bounded retry policy.
_RECONCILIATION_DELAYS = (0.1, 0.15, 0.25)


async def async_reconcile(
    readback: Callable[[], Awaitable[DeviceSnapshot]], wait: Callable[[float], Awaitable[None]], complete: CompletionPredicate,
) -> None:
    """Observe immediately, then retry only incomplete observations within one finite budget.

    The caller owns publication and transaction/I/O lifetime. A mismatch at the
    budget boundary is not write failure; read and predicate failures propagate.
    This operation never issues or replays a mutation.
    """
    if complete(await readback()):
        return
    for delay in _RECONCILIATION_DELAYS:
        await wait(delay)
        if complete(await readback()):
            return


class SihasCommands:
    """One command transaction owner for one ConfigEntry's physical device.

    The lock spans an entire operation, its evidenced waits and reconciliation.
    Ordinary coordinator reads remain independent: they publish real observations,
    while state-dependent commands retain their starting immutable publication.
    There is no optimistic state or generic command plan.
    A final write or command-read failure fails the logical operation: no later
    step of that operation runs and nothing is rolled back or compensated.
    Periodic polling remains the independent reconciliation of device state.

    Device-family command sequencing and value selection are the published
    definition's feature policies under `devices/*`; this owner only admits,
    serializes, executes and reconciles the resulting effects.
    """

    def __init__(self, client: SihasClient, coordinator: SihasCoordinator, device_type: str,
                 command_metadata: CommandMetadata | None = None) -> None:
        self._client = client
        self._coordinator = coordinator
        self._device_type = device_type
        self._command_metadata = command_metadata
        self._lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._generation = 0

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        """Reject stale admissions, including waiters from an aborted unload."""
        generation = self._generation
        if self._closing:
            raise RuntimeError("SiHAS command owner is unloading")
        async with self._lock:
            if self._closing or generation != self._generation:
                raise RuntimeError("SiHAS command owner is unloading")
            yield

    async def async_quiesce(self) -> None:
        """Stop admission before waiting for the active logical operation to finish."""
        if not self._closing:
            self._closing = True
            self._generation += 1
        async with self._lock:
            pass

    def resume(self) -> None:
        """Restore this same owner only when unload failed or was aborted."""
        if not self._closed:
            self._closing = False

    async def async_shutdown(self) -> None:
        """Permanently quiesce the owner; safe to call again during HA cleanup."""
        await self.async_quiesce()
        self._closed = True

    async def _finish_io(self, operation: Coroutine[Any, Any, _Result]) -> _Result:
        """Drain issued I/O before releasing a cancelled transaction.

        Cancelling the caller cannot stop an executor socket operation. Wait for
        the issued operation without cancelling it; cancellation stops the
        remaining sequence after this bounded I/O completes. Repeated cancellation
        must not let a later command overtake an outstanding physical write.
        """
        pending = asyncio.create_task(operation)
        try:
            await asyncio.wait({pending})
        except asyncio.CancelledError:
            while not pending.done():
                try:
                    await asyncio.wait({pending})
                except asyncio.CancelledError:
                    continue
            if not pending.cancelled():
                pending.exception()
            raise
        return pending.result()

    async def async_diagnostic_read(self, trace: ExchangeTrace) -> tuple[int, ...]:
        """Admit one fresh read under device lifecycle/command ownership.

        No publication or command refresh follows this read. Ordinary coordinator
        polls remain independent. The same admission generation and I/O drain
        protect diagnostics against unload, stale waiters and cancellation.
        """
        async with self._transaction():
            return tuple(await self._finish_io(self._client.async_poll(trace=trace)))

    async def _command_io(self, operation: Coroutine[Any, Any, _Result], action: str) -> _Result:
        """Report a final command I/O failure to HA as an action failure; cancellation stays cancellation."""
        try:
            return await self._finish_io(operation)
        except Exception as err:
            raise HomeAssistantError(f"SiHAS {self._device_type} {action} failed: {err}") from err

    async def _write(self, intent: tuple[int, int]) -> None:
        """Register-write effect with normal client retry policy; final failure propagates."""
        _LOGGER.debug("Command intent device_type=%s register=%s value=%s", self._device_type, *intent)
        await self._command_io(self._client.async_command(*intent, retry=3), f"write to register {intent[0]}")

    async def _write_once(self, intent: tuple[int, int]) -> None:
        """Register-write effect with one timeout attempt; client PID handling is unchanged."""
        _LOGGER.debug("Command intent device_type=%s register=%s value=%s", self._device_type, *intent)
        await self._command_io(self._client.async_command(*intent, retry=1), f"write to register {intent[0]}")

    async def _refresh(self) -> None:
        """Publish readback after an operation whose owner requests an immediate follow-up."""
        await self._finish_io(self._coordinator.async_refresh())

    async def _readback(self) -> DeviceSnapshot:
        """Publish a required command observation without accepting retained data after a failed refresh."""
        await self._refresh()
        if not self._coordinator.last_update_success:
            error = self._coordinator.last_exception
            raise HomeAssistantError(f"SiHAS {self._device_type} readback failed: {error}") from error
        return self._coordinator.data

    async def _reconcile(self, complete: CompletionPredicate) -> None:
        await async_reconcile(self._readback, asyncio.sleep, complete)

    async def _multi_control(self, commands: CommandPairs, *, retry: int = 3) -> None:
        """Execute manufacturer command-list effects under the same I/O drain and error boundary."""
        if self._command_metadata is None:
            raise ValueError("Manufacturer command-list metadata is unavailable")
        if self._command_metadata.ssid is None:
            # The device accepts command lists only with its own network SSID, which it does not report.
            _LOGGER.error("SiHAS %s (%s) needs the Wi-Fi SSID for this control. Enter the case-sensitive name of the Wi-Fi network "
                          "the device is joined to via the integration entry's Reconfigure action.", self._device_type, self._coordinator.name)
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="ssid_not_configured")
        for index, value in commands:
            _LOGGER.debug("Command intent device_type=%s register=%s value=%s", self._device_type, index, value)
        await self._command_io(self._client.async_multi_control(self._command_metadata, commands, retry=retry), "multi-control")

    async def _multi_control_once(self, commands: CommandPairs) -> None:
        await self._multi_control(commands, retry=1)

    async def _read(self) -> tuple[int, ...]:
        """One fresh complete read inside the held transaction; no publication, failures propagate."""
        return tuple(await self._command_io(self._client.async_poll(), "read"))

    async def async_execute(self, feature: str, value: CommandValue) -> None:
        """Run the published definition's policy inside the existing transaction.

        The policy receives the transaction-start publication. The refresh effect
        publishes device readback, and the read effect returns an unpublished fresh
        register tuple for policies that verify intermediate device state; there is
        no optimistic state.
        """
        async with self._transaction():
            snapshot = self._coordinator.data
            if snapshot is None or snapshot.definition is None:
                raise ValueError("No device definition has been published")
            execution = CommandExecution(self._write, asyncio.sleep, self._write_once, self._refresh, self._read,
                                         self._multi_control, self._multi_control_once, self._reconcile)
            await snapshot.definition.async_execute(feature, value, snapshot, execution)
