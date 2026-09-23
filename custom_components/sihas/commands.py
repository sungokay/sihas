"""Per-device operations, preserving the verified write/wait/refresh sequences."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
import logging
from typing import Any, TypeVar

from .client import SihasClient
from .coordinator import SihasCoordinator
from .trace import ExchangeTrace
from .devices import acm, ccm, hqm, rbm, sdm, tcm
from .devices.definition import CommandExecution, CommandValue
from .devices.state import light_command_owner, room_command_owner

_LOGGER = logging.getLogger(__name__)
_Result = TypeVar("_Result")


class SihasCommands:
    """One command transaction owner for one ConfigEntry's physical device.

    The lock spans an entire operation, its evidenced waits and reconciliation.
    Ordinary coordinator reads remain independent: they publish real observations,
    while state-dependent commands retain their starting immutable publication.
    There is no optimistic state, generic command plan or extra polling policy.

    Device-family command sequencing, value selection and per-family routing are
    owned by `devices/*`; this owner only admits, serializes, executes and
    reconciles the resulting physical writes.
    """

    def __init__(self, client: SihasClient, coordinator: SihasCoordinator, device_type: str) -> None:
        self._client = client
        self._coordinator = coordinator
        self._device_type = device_type
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

    async def _write(self, intent: tuple[int, int]) -> bool:
        """Retain the existing retry=3 best-effort consequence inside a transaction."""
        try:
            _LOGGER.debug("Command intent device_type=%s register=%s value=%s", self._device_type, *intent)
            await self._finish_io(self._client.async_command(*intent, retry=3))
        except Exception as err:
            _LOGGER.warning("Failed to command %s: %s", self._device_type, err)
            return False
        return True

    async def _write_once(self, intent: tuple[int, int]) -> None:
        """One physical attempt; preserve failure and drain any issued I/O."""
        _LOGGER.debug("Command intent device_type=%s register=%s value=%s", self._device_type, *intent)
        await self._finish_io(self._client.async_command(*intent, retry=1))

    async def _refresh(self) -> None:
        """Only operations with an evidenced immediate follow-up call this."""
        await self._finish_io(self._coordinator.async_refresh())

    async def async_acm_mode(self, mode: str) -> None:
        async with self._transaction():
            snapshot = self._coordinator.data
            previous_mode = snapshot.state.mode if snapshot is not None else None
            await acm.async_mode_transition(previous_mode, mode, CommandExecution(self._write, asyncio.sleep, self._write_once))

    async def async_acm_temperature(self, temperature: float) -> None:
        async with self._transaction():
            await self._write(acm.temperature_command(temperature))

    async def async_acm_fan(self, mode: str) -> None:
        async with self._transaction():
            await self._write(acm.fan_command(mode))

    async def async_acm_swing(self, mode: str) -> None:
        async with self._transaction():
            await self._write(acm.swing_command(mode))

    async def async_acm_remote(self, index: int) -> None:
        async with self._transaction():
            await self._write(acm.remote_command(index))

    async def async_bcm_mode(self, mode: str) -> None:
        """Use domain mode names; HA's AUTO/HEAT/FAN_ONLY mapping stays in HA."""
        await self.async_execute("mode", mode)

    async def async_bcm_temperature(self, temperature: float) -> None:
        await self.async_execute("temperature", temperature)

    async def async_bcm_occupancy(self, option: str) -> None:
        await self.async_execute("occupancy", option)

    async def async_bcm_schedule(self, enabled: bool) -> None:
        await self.async_execute("schedule", enabled)

    async def async_execute(self, feature: str, value: CommandValue) -> None:
        """Run the published definition's policy inside the existing transaction."""
        async with self._transaction():
            snapshot = self._coordinator.data
            if snapshot is None or snapshot.definition is None:
                raise ValueError("No device definition has been published")
            await snapshot.definition.async_execute(feature, value, snapshot, CommandExecution(self._write, asyncio.sleep, self._write_once))

    async def async_tcm_mode(self, mode: str) -> None:
        async with self._transaction():
            await tcm.async_mode_transition(mode, CommandExecution(self._write, asyncio.sleep, self._write_once))

    async def async_tcm_temperature(self, temperature: float) -> None:
        async with self._transaction():
            await self._write(tcm.temperature_command(temperature))

    async def async_room_power(self, room: int, powered: bool) -> None:
        async with self._transaction():
            owner = room_command_owner(self._device_type)
            index = owner.room_register(room)
            word = self._coordinator.data.registers[index]
            await self._write((index, owner.room_power(word, powered)))
            await self._refresh()

    async def async_room_temperature(self, room: int, temperature: float) -> None:
        async with self._transaction():
            snapshot = self._coordinator.data
            owner = room_command_owner(self._device_type)
            index = owner.room_register(room)
            state = owner.room_state(snapshot.state, room)
            await self._write((index, owner.room_target(snapshot.registers[index], temperature, state.temperature_step)))
            await self._refresh()

    async def async_hqm_power(self, powered: bool) -> None:
        async with self._transaction():
            await self._write(hqm.hqm_power_command(powered))
            await self._refresh()

    async def async_hqm_temperature(self, temperature: float) -> None:
        async with self._transaction():
            await self._write(hqm.hqm_temperature_command(temperature))
            await self._refresh()

    async def async_light_power(self, channel: int, powered: bool) -> None:
        async with self._transaction():
            owner = light_command_owner(self._device_type)
            await self._write(owner.switch_command(channel, powered))
            await self._refresh()

    async def async_dimmer_on(self, channel: int, level: int | None = None) -> None:
        async with self._transaction():
            await self._write(sdm.dimmer_on_intent(channel, level))
            await self._refresh()

    async def async_dimmer_off(self, channel: int) -> None:
        async with self._transaction():
            await self._write(sdm.dimmer_off_command(channel))
            await self._refresh()

    async def async_ccm_power(self, powered: bool) -> None:
        async with self._transaction():
            await ccm.async_power(powered, CommandExecution(self._write, asyncio.sleep, self._write_once))

    async def async_rbm_motion(self, motion: str) -> None:
        async with self._transaction():
            await self._write(rbm.rbm_motion_command(motion))

    async def async_rbm_position(self, position: int) -> None:
        async with self._transaction():
            await self._write(rbm.rbm_position_command(position))
