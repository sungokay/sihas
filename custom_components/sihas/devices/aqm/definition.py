"""AQM family composition of read semantics and command policies."""
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import partial

from . import actions as aqm_actions
from . import controls as aqm_controls
from . import link_toggle as aqm_link_toggle
from . import state as aqm_state
from .metadata import display_for
from ..definition import DeviceDefinition, Feature


def _catalog(config: int | None) -> Mapping[str, Feature]:
    """Every approved AQM command feature for this configured display interpretation."""
    return {
        **{key: Feature(command=partial(aqm_actions.execute, key)) for key in aqm_actions.ACTION_INTENTS},
        **{key: Feature(read_supported=True, command=command) for key, command in aqm_controls.commands(display_for(config)).items()},
        **{key: Feature(read_supported=True, command=command) for key, command in aqm_link_toggle.commands().items()},
    }


def command_keys(config: int | None = None) -> tuple[str, ...]:
    """The command features production preparation attaches for this configured fact."""
    return tuple(_catalog(config))


def compose(*, config: int | None = None, firmware: str | None = None, commands: Collection[str] = ()) -> DeviceDefinition:
    """Compose the read decoder with exactly the named AQM command features.

    Production preparation names every approved command; an explicit subset is a
    composition input, never inferred from metadata or register reads. A key the
    configured display interpretation does not offer is rejected.
    """
    catalog = _catalog(config)
    if any(key not in catalog for key in commands):
        raise ValueError("Unknown AQM command feature")
    return DeviceDefinition(
        decode=partial(aqm_state.decode_aqm, config=config, firmware=firmware),
        features={key: catalog[key] for key in commands},
    )


@dataclass(frozen=True)
class Prepared:
    """One runtime's configured facts and definition; firmware text is metadata only."""

    config: int | None
    firmware: str | None
    definition: DeviceDefinition


def prepare(*, config: int | None = None, firmware: str | None = None) -> Prepared:
    """Compose once with every approved AQM command policy.

    The one-shot actions, the evidence-backed setting writers and the ten link
    rule toggles are the family command contract for every AQM entry. Only the configured display
    interpretation (config) selects the LCD-only primary-display writer; firmware
    text and mutable R8/R9 words never select or remove a command.
    """
    return Prepared(config, firmware, compose(config=config, firmware=firmware, commands=command_keys(config)))


def resolve(registers: Sequence[int], prepared: Prepared) -> DeviceDefinition:
    """The same prepared definition for every snapshot; no register selects AQM semantics."""
    return prepared.definition
