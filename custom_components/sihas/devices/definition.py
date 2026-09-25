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
    write_once is an optional strict single-attempt effect, with propagated errors.
    refresh is an optional coordinator refresh that publishes the device readback.
    Policies requiring an optional effect must reject its absence instead of
    falling back to another effect.
    """

    write: Callable[[tuple[int, int]], Awaitable[bool]]
    wait: Callable[[float], Awaitable[None]]
    write_once: Callable[[tuple[int, int]], Awaitable[None]] | None = None
    refresh: Callable[[], Awaitable[None]] | None = None


CommandPolicy = Callable[["DeviceSnapshot", CommandValue, CommandExecution], Awaitable[None]]


@dataclass(frozen=True)
class Feature:
    """One support fact: read support and an allowed command are independent.

    Reading alone never allows a write, and an action may have a command without
    a read state. A present entry with neither is not support. An attached command
    is an allowed policy, not physical write acceptance; that evidence stays in
    the validation records. Device-reported values and limits belong to decoded
    state, not this metadata.
    """

    read_supported: bool = False
    command: CommandPolicy | None = None

    @property
    def can_write(self) -> bool:
        return self.command is not None


@dataclass(frozen=True)
class DeviceDefinition:
    """A decoder and explicitly composed features, without implicit base behavior.

    The feature map is the single support authority for the surfaces it names;
    HA presentation and command admission query it rather than keeping copies.
    """

    decode: Callable[[Sequence[int]], DeviceState]
    features: Mapping[str, Feature]

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))

    def can_write(self, feature: str) -> bool:
        """Whether this definition attaches an allowed command policy to `feature`."""
        capability = self.features.get(feature)
        return capability is not None and capability.can_write

    async def async_execute(
        self, feature: str, value: CommandValue, snapshot: DeviceSnapshot, execution: CommandExecution,
    ) -> None:
        """Reject absent features and features without a command before applying the selected policy."""
        capability = self.features.get(feature)
        if capability is None or capability.command is None:
            raise ValueError(f"Device feature has no command policy: {feature}")
        await capability.command(snapshot, value, execution)


DefinitionResolver = Callable[[Sequence[int]], DeviceDefinition]
