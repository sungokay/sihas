"""Static device-family registry: the only place that associates a type identifier with its parts.

Adding or removing a family touches its `devices/**` semantic owner, its module here and one entry below.
"""
from __future__ import annotations

from types import MappingProxyType

from . import acm, aqm, bcm, ccm, hcm, hqm, hvm, pmm, rbm, rcm, sbm, sdm, sqm, stm, tcm
from .registration import FamilyRegistration
from ..devices.state import DeviceBinding

FAMILIES: MappingProxyType[str, FamilyRegistration] = MappingProxyType({
    "ACM": acm.FAMILY, "AQM": aqm.FAMILY, "BCM": bcm.FAMILY, "CCM": ccm.FAMILY, "HCM": hcm.FAMILY, "HQM": hqm.FAMILY,
    "HVM": hvm.FAMILY, "PMM": pmm.FAMILY, "RBM": rbm.FAMILY, "RCM": rcm.FAMILY, "SBM": sbm.FAMILY, "SDM": sdm.FAMILY,
    "SQM": sqm.FAMILY, "STM": stm.FAMILY, "TCM": tcm.FAMILY,
})


def prepare(device_type: str, config: int, *, firmware: str | None = None) -> DeviceBinding | None:
    """Bind a registered family's semantics; an identifier without semantics has no binding."""
    family = FAMILIES[device_type]
    return family.prepare(config, firmware) if family.prepare is not None else None
