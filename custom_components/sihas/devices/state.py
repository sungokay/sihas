"""Shared snapshots composed exclusively from the existing device decoders."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from . import acm, ccm, hcm, hqm, pmm, rbm, sbm, sdm, sqm, stm, tcm
from .aqm import definition as aqm_definition
from .aqm import state as aqm_state
from .bcm import definition as bcm_definition
from .bcm import metadata as bcm_metadata
from .bcm import state as bcm_state
from .definition import DefinitionResolver, DeviceDefinition
from .hvm import observation as hvm_observation
from .hvm import summary as hvm_summary
from .metadata import MetadataReader

DeviceState = (
    acm.AcmState | bcm_state.BcmState | hqm.HqmState | tcm.TcmState
    | aqm_state.AqmState | pmm.PmmState | ccm.CcmState | rbm.RbmState
    | tuple[hcm.RoomState, ...] | hvm_observation.HvmSummaryState | tuple[sdm.DimmerState, ...] | tuple[bool, ...]
)
StateDecoder = Callable[[Sequence[int]], DeviceState]


@dataclass(frozen=True)
class DeviceSnapshot:
    """One complete read with decoded state and the raw words needed by commands."""

    registers: tuple[int, ...]
    state: DeviceState
    definition: DeviceDefinition | None = None


@dataclass(frozen=True)
class DeviceBinding:
    """Semantics prepared once from one setup's configured facts; no I/O.

    `decode` decodes a snapshot when no `resolve` is bound; `resolve` selects a
    definition-based family's definition from each snapshot; `prepared` is the
    family-owned choice record that its Diagnostics interpretation consumes;
    `metadata` optionally reads display overrides from a decoded state, and its
    absence keeps every common device-information default.
    """

    decode: StateDecoder
    resolve: DefinitionResolver | None = None
    prepared: object | None = None
    metadata: MetadataReader | None = None


def prepare(device_type: str, config: int, *, firmware: str | None = None) -> DeviceBinding | None:
    """Route family preparation; firmware interpretation ends inside the family.

    Only already-implemented variation is bound; unsupported types have no binding.
    """
    match device_type:
        case "AQM":
            aqm = aqm_definition.prepare(config=config, firmware=firmware)
            return DeviceBinding(aqm.definition.decode, partial(aqm_definition.resolve, prepared=aqm), aqm)
        case "BCM":
            bcm = bcm_definition.prepare(firmware)
            return DeviceBinding(partial(bcm_definition.decode, prepared=bcm), partial(bcm_definition.resolve, prepared=bcm), bcm,
                                 bcm_metadata.display)
        case "HVM":
            hvm = hvm_observation.prepare(firmware)
            return DeviceBinding(partial(hvm_observation.decode_summary, prepared=hvm), prepared=hvm)
    decoder = _state_decoder(device_type, config)
    return DeviceBinding(decoder) if decoder is not None else None


def _state_decoder(device_type: str, config: int) -> StateDecoder | None:
    """Bind only already-implemented device variation for families without firmware choices."""
    match device_type:
        case "ACM":
            return partial(acm.decode, config=config)
        case "CCM":
            return ccm.decode_ccm
        case "HCM":
            return hcm.decode
        case "HQM":
            return partial(hqm.decode_hqm, config=config)
        case "PMM":
            return pmm.decode_pmm
        case "RBM":
            return rbm.decode_rbm
        case "STM":
            return partial(stm.decode_switches, config=config)
        case "SBM":
            return partial(sbm.decode_switches, config=config)
        case "SQM":
            return partial(sqm.decode_switches, config=config)
        case "SDM":
            return partial(sdm.decode_dimmers, config=config)
        case "TCM":
            return tcm.decode
        case _:
            return None


def room_command_owner(device_type: str):
    """Resolve the family module owning room register/state/power/temperature intent."""
    if device_type == "HQM":
        return hqm
    if device_type == "HCM":
        return hcm
    return hvm_summary


def light_command_owner(device_type: str):
    """Resolve the family module owning per-channel switch command intent."""
    if device_type == "STM":
        return stm
    if device_type == "SBM":
        return sbm
    return sqm
