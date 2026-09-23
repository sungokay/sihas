"""Composed device semantics; no HA, transport or lifecycle ownership."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import DeviceSnapshot, DeviceState

CommandValue = str | float | bool


@dataclass(frozen=True)
class CommandExecution:
    """Runtime-provided effects; policies own intent, runtime owns I/O.

    write retains the runtime's existing best-effort retry/failure and I/O drain
    contract. wait is an interruptible asynchronous delay inside the transaction.
    BCM requires no immediate readback; publication stays with ordinary polling.
    write_once is an optional strict single-attempt effect, with propagated errors.
    Policies requiring it must reject its absence instead of falling back to write.
    """

    write: Callable[[tuple[int, int]], Awaitable[bool]]
    wait: Callable[[float], Awaitable[None]]
    write_once: Callable[[tuple[int, int]], Awaitable[None]] | None = None


CommandPolicy = Callable[["DeviceSnapshot", CommandValue, CommandExecution], Awaitable[None]]


@dataclass(frozen=True)
class Feature:
    """Partial knowledge: reading alone never qualifies a write.

    Attaching a command is an explicit assertion of verified writable policy.
    Unknown features are omitted or have neither read support nor a command.
    Device-reported values and limits belong to decoded state, not this metadata.
    """

    read_supported: bool = False
    command: CommandPolicy | None = None

    @property
    def write_qualified(self) -> bool:
        return self.command is not None


@dataclass(frozen=True)
class DeviceDefinition:
    """A decoder and explicitly composed features, without implicit base behavior."""

    decode: Callable[[Sequence[int]], DeviceState]
    features: Mapping[str, Feature]

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))

    async def async_execute(
        self, feature: str, value: CommandValue, snapshot: DeviceSnapshot, execution: CommandExecution,
    ) -> None:
        """Reject absent/unqualified writes before applying the selected policy."""
        capability = self.features.get(feature)
        if capability is None or capability.command is None:
            raise ValueError(f"Device feature is not write-qualified: {feature}")
        await capability.command(snapshot, value, execution)


DefinitionResolver = Callable[[Sequence[int]], DeviceDefinition]
