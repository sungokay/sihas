"""Shared snapshot and binding contracts; family routing lives in the static family registry."""

from dataclasses import dataclass

from .definition import DefinitionResolver, DeviceDefinition
from .metadata import MetadataReader

# Each family owns its decoded state type; common code never enumerates the families.
DeviceState = object


@dataclass(frozen=True)
class DeviceSnapshot:
    """One complete read with decoded state and the raw words needed by commands."""

    registers: tuple[int, ...]
    state: DeviceState
    definition: DeviceDefinition | None = None


@dataclass(frozen=True)
class DeviceBinding:
    """Semantics prepared once from one setup's configured facts; no I/O.

    `resolve` selects the family definition (decoder and commands) for each
    snapshot; `prepared` is the family-owned choice record that its Diagnostics
    interpretation consumes; `metadata` optionally reads display overrides from a
    decoded state, and its absence keeps every common device-information default.
    """

    resolve: DefinitionResolver
    prepared: object | None = None
    metadata: MetadataReader | None = None
