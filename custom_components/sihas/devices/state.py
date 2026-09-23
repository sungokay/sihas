"""Shared snapshots composed exclusively from the existing device decoders."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from . import acm, ccm, hcm, hqm, pmm, rbm, sbm, sdm, sqm, stm, tcm
from .aqm import definition as aqm_definition
from .aqm import state as aqm_state
from .bcm import definition as bcm_definition
from .bcm import state as bcm_state
from .definition import DefinitionResolver, DeviceDefinition
from .hvm import observation as hvm_observation
from .hvm import summary as hvm_summary

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


def definition_resolver(device_type: str, config: int | None = None, *, firmware: str | None = None) -> DefinitionResolver | None:
    """Route migrated families only; concrete model matching stays family-owned."""
    if device_type == "AQM":
        return partial(aqm_definition.resolve, config=config, firmware=firmware)
    if device_type == "BCM":
        return bcm_definition.resolve
    return None


def state_decoder(device_type: str, config: int, *, firmware: str | None = None) -> StateDecoder | None:
    """Bind only already-implemented device variation; unsupported types have no decoder."""
    match device_type:
        case "ACM":
            return partial(acm.decode, config=config)
        case "AQM":
            return partial(aqm_state.decode_aqm, config=config, firmware=firmware)
        case "BCM":
            return bcm_definition.decode
        case "CCM":
            return ccm.decode_ccm
        case "HCM":
            return hcm.decode
        case "HVM":
            return hvm_observation.decode_summary
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
