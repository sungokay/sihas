"""SBM Home Assistant presentation owner."""
from __future__ import annotations

from homeassistant.const import Platform

from .registration import FamilyRegistration
from ..devices import sbm as sbm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..light import StmSbm300

# Per-channel on/off lights share the common light presentation.
FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(sbm_semantics.definition(config))),
    entities={Platform.LIGHT: lambda runtime: StmSbm300(runtime).get_sub_entities()},
)
