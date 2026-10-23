"""One static device-family registration entry."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.const import Platform
from homeassistant.helpers.entity import Entity

from ..devices.state import DeviceBinding
from ..devices.sensitive import SensitiveField
from ..runtime import SihasRuntime

EntityFactory = Callable[[SihasRuntime], list[Entity]]
Interpreter = Callable[[tuple[int, ...], Any], dict]


@dataclass(frozen=True)
class FamilyRegistration:
    """Everything common code needs to know about one accepted type identifier.

    `prepare` binds the family semantics from configured CFG and firmware; an accepted
    identifier without evidenced semantics has none and gets no runtime. `entities`
    maps each HA platform the family uses to its presentation factory.
    """

    prepare: Callable[[int, str | None], DeviceBinding] | None = None
    poll_interval: timedelta = timedelta(seconds=5)
    first_refresh_retry: int = 3
    diagnostics: Interpreter | None = None
    sensitive: tuple[SensitiveField, ...] = ()
    entities: Mapping[Platform, EntityFactory] = field(default_factory=dict)
