"""BCM device-information display from the already decoded controller identity."""
from __future__ import annotations

from . import state as bcm
from ..metadata import DeviceMetadata

# Human-readable labels for the makers of the controller table.
_MANUFACTURER_LABELS = {
    bcm.BoilerManufactuer.KYUNGDONG: "Kyungdong", bcm.BoilerManufactuer.KITURAMI: "Kiturami",
    bcm.BoilerManufactuer.DAESUNG: "Daesung", bcm.BoilerManufactuer.RINNAI: "Rinnai", bcm.BoilerManufactuer.DMAX: "DMAX",
}


def display(state: bcm.BcmState) -> DeviceMetadata:
    """Show the identified boiler manufacturer and controller together, or neither.

    Only a valid R15/R16 identity of the controller table qualifies; unknown, missing or
    invalid identity keeps both common values. The displayed controller implies no
    writer support or physical qualification. Firmware stays the SiHAS module's own.
    """
    identity = state.identity
    label = _MANUFACTURER_LABELS.get(state.manufacturer) if isinstance(state.manufacturer, bcm.BoilerManufactuer) else None
    if identity.quality != "valid" or identity.controller is None or label is None:
        return DeviceMetadata()
    return DeviceMetadata(manufacturer=label, model=identity.controller)
