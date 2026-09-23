"""Minimal AQM composition. No production action has physical qualification."""
from collections.abc import Collection, Sequence
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


def resolve(registers: Sequence[int], *, config: int | None = None, firmware: str | None = None) -> DeviceDefinition:
    """Retain all read semantics; cfg/firmware/R8/R9 never qualify a writer."""
    return compose(config=config, firmware=firmware)
