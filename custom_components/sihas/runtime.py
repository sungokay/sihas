"""ConfigEntry-owned communication and device configuration."""

from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

from homeassistant.config_entries import ConfigEntry

from .client import SihasClient
from .commands import SihasCommands
from .coordinator import SihasCoordinator
from .devices.metadata import DeviceMetadata
from .devices.state import DeviceBinding, DeviceSnapshot

DEFAULT_MANUFACTURER = "SiHAS"


@dataclass(frozen=True)
class SihasDeviceConfig:
    """Configured facts, separate from live state and device decoding.

    The canonical MAC identifies the physical device. CFG is only the existing
    device configuration discriminator; it never contributes to identity.
    """

    ip: str
    mac: str
    device_type: str
    config: int
    name: str
    firmware: str | None = None
    firmware_source: str | None = None
    firmware_observed_at: str | None = None


@dataclass(frozen=True)
class DeviceIdentification:
    """Identification facts of this setup for the device model; never operational input.

    `scan` records the textual observation accepted during this setup; `config`
    records the configured facts used when no observation was accepted. Its CFG is
    displayed as-is: a reported CFG or IP never replaces the configured CFG,
    capability preparation, commands or the transport endpoint.
    """

    source: Literal["scan", "config"]
    device_type: str
    firmware: str | None
    mac: str
    ip: str
    config: int

    @classmethod
    def of(cls, facts: SihasDeviceConfig, source: Literal["scan", "config"]) -> "DeviceIdentification":
        return cls(source, facts.device_type, facts.firmware, facts.mac, facts.ip, facts.config)


def resolve_device_metadata(device: SihasDeviceConfig, identification: DeviceIdentification,
                            binding: DeviceBinding | None, snapshot: DeviceSnapshot | None) -> DeviceMetadata:
    """Combine common defaults, optional family overrides and the identification CFG.

    Defaults are manufacturer SiHAS, the configured family as base model and the
    observed-or-retained firmware; missing firmware stays absent. Each override field
    replaces only its own default. The model is `<base>/<family>/<cfg>`, omitting the
    family when the base model already is the family; CFG is the uninterpreted
    decimal value. The result is display text for HA device information only; no
    behavior reads it.
    """
    override = DeviceMetadata()
    if binding is not None and binding.metadata is not None and snapshot is not None:
        override = binding.metadata(snapshot.state)
    manufacturer = override.manufacturer if override.manufacturer is not None else DEFAULT_MANUFACTURER
    model = override.model if override.model is not None else device.device_type
    firmware = override.firmware if override.firmware is not None else device.firmware
    base = model if model == device.device_type else f"{model}/{device.device_type}"
    return DeviceMetadata(manufacturer, f"{base}/{identification.config}", firmware)


@dataclass(frozen=True)
class SihasRuntime:
    """Shared client, command owner and device configuration for one loaded entry.

    The coordinator owns shared refresh when consumers subscribe. HA shuts it
    down through the ConfigEntry lifecycle; transport sockets remain request-scoped.
    The integration unload callback releases the entry's runtime reference.
    Accepted types without evidenced semantics have no coordinator or command owner.
    `binding` retains the family semantics prepared for this runtime; its
    consumers never reinterpret the configured firmware. `identification` is the
    setup's display-only identification; without one the configured facts apply.
    """

    client: SihasClient
    device: SihasDeviceConfig
    coordinator: SihasCoordinator | None
    binding: DeviceBinding | None = None
    identification: DeviceIdentification | None = None
    commands: SihasCommands | None = field(init=False)

    def __post_init__(self) -> None:
        # Runtime construction binds exactly one command owner to its existing
        # client/coordinator; every platform receives this same instance.
        object.__setattr__(self, "commands", SihasCommands(self.client, self.coordinator, self.device.device_type)
                           if self.coordinator is not None else None)

    @cached_property
    def device_metadata(self) -> DeviceMetadata:
        """The one device-information projection registered by every entity of this runtime.

        Resolved once from the publication current at first use; root setup resolves it
        right after the first refresh, so all platforms register the same values. A
        reload builds a new runtime and projection. Polling and commands never read it.
        """
        identification = self.identification or DeviceIdentification.of(self.device, "config")
        snapshot = self.coordinator.data if self.coordinator is not None else None
        return resolve_device_metadata(self.device, identification, self.binding, snapshot)


SihasConfigEntry = ConfigEntry[SihasRuntime]
