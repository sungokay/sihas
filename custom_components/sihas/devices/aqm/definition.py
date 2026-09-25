"""Minimal AQM composition. No production action has physical qualification."""
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from functools import partial

from . import actions as aqm_actions
from . import state as aqm_state
from ..definition import DeviceDefinition, Feature


def compose(*, config: int | None = None, firmware: str | None = None, qualified_actions: Collection[str] = ()) -> DeviceDefinition:
    """Explicitly compose independently qualified keys; callers own the evidence.

    Production resolution supplies no qualified actions. Synthetic qualification
    is only an explicit test input, never inferred from metadata or register reads.
    """
    if any(key not in aqm_actions.ACTION_INTENTS for key in qualified_actions):
        raise ValueError("Unknown AQM action qualification")
    return DeviceDefinition(
        decode=partial(aqm_state.decode_aqm, config=config, firmware=firmware),
        features={key: Feature(command=partial(aqm_actions.execute, key)) for key in qualified_actions},
    )


@dataclass(frozen=True)
class Prepared:
    """One runtime's configured facts and read definition; firmware text is metadata only."""

    config: int | None
    firmware: str | None
    definition: DeviceDefinition


def prepare(*, config: int | None = None, firmware: str | None = None) -> Prepared:
    """Compose once: retain all read semantics; cfg/firmware/R8/R9 never qualify a writer."""
    return Prepared(config, firmware, compose(config=config, firmware=firmware))


def resolve(registers: Sequence[int], prepared: Prepared) -> DeviceDefinition:
    """The same prepared definition for every snapshot; no register selects AQM semantics."""
    return prepared.definition
