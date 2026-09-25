"""BCM device-information display from the already decoded controller identity."""
from __future__ import annotations

from . import state as bcm
from ..metadata import DeviceMetadata

# Human-readable labels only for manufacturers of an evidenced controller identity.
_MANUFACTURER_LABELS = {bcm.BoilerManufactuer.KYUNGDONG: "Kyungdong"}


def display(state: bcm.BcmState) -> DeviceMetadata:
    """Show the identified boiler manufacturer and controller together, or neither.

    Only a valid, evidenced R15/R16 controller identity qualifies; unknown, missing or
    invalid identity keeps both common values. The displayed controller implies no
    writer support or physical qualification. Firmware stays the SiHAS module's own.
    """
    identity = state.identity
    label = _MANUFACTURER_LABELS.get(state.manufacturer) if isinstance(state.manufacturer, bcm.BoilerManufactuer) else None
    if identity.quality != "valid" or identity.controller is None or label is None:
        return DeviceMetadata()
    return DeviceMetadata(manufacturer=label, model=identity.controller.value)
