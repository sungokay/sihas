"""ConfigEntry-owned communication and device configuration."""

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry

from .client import SihasClient
from .commands import SihasCommands
from .coordinator import SihasCoordinator
from .devices.state import DeviceBinding


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
class SihasRuntime:
    """Shared client, command owner and device configuration for one loaded entry.

    The coordinator owns shared refresh when consumers subscribe. HA shuts it
    down through the ConfigEntry lifecycle; transport sockets remain request-scoped.
    The integration unload callback releases the entry's runtime reference.
    Accepted types without evidenced semantics have no coordinator or command owner.
    `binding` retains the family semantics prepared for this runtime; its
    consumers never reinterpret the configured firmware.
    """

    client: SihasClient
    device: SihasDeviceConfig
    coordinator: SihasCoordinator | None
    binding: DeviceBinding | None = None
    commands: SihasCommands | None = field(init=False)

    def __post_init__(self) -> None:
        # Runtime construction binds exactly one command owner to its existing
        # client/coordinator; every platform receives this same instance.
        object.__setattr__(self, "commands", SihasCommands(self.client, self.coordinator, self.device.device_type)
                           if self.coordinator is not None else None)


SihasConfigEntry = ConfigEntry[SihasRuntime]
