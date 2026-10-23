"""Executor-safe discovery and runtime composition shared by flows and ConfigEntry setup.

One HA-instance service supplies discovery and register transports to workflows.
The transports are normal composition contracts: textual discovery is deliberately
separate from the register client's DatagramTransport. Neither validates new
capabilities or interprets additional device semantics.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, UTC
from functools import partial
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .client import SihasClient
from .config_facts import device_config, UnsupportedDeviceType
from .const import CONF_FIRMWARE, CONF_MAC
from .coordinator import SihasCoordinator
from .families import FAMILIES
from .protocol.discovery import DiscoveryTransport, UdpDiscoveryTransport
from .protocol.packet import packet_builder
from .protocol.transport import DatagramTransport, UdpTransport
from .runtime import DeviceIdentification, SihasDeviceConfig, SihasRuntime
from .util import canonical_mac, parse_scan_message

_LOGGER = logging.getLogger(__name__)


class DeviceIdentityMismatch(ValueError):
    """The scan's canonical MAC does not match the discovered physical device."""


class SihasComposition:
    """Production composition shared by flows and ConfigEntry runtime setup.

    A transport factory binds each new runtime to its configured endpoint. Textual
    discovery has its own transport because its protocol and retry policy differ.
    Register validation always uses SihasCoordinator and its existing client.
    """

    def __init__(
        self, hass: HomeAssistant, transport_factory: Callable[[str], DatagramTransport] = UdpTransport,
        discovery: DiscoveryTransport | None = None,
    ) -> None:
        self.hass = hass
        self.transport_factory = transport_factory
        self.discovery = discovery if discovery is not None else UdpDiscoveryTransport()

    async def async_identify(self, ip: str, expected_mac: str, *, attempts: int = 10) -> SihasDeviceConfig | None:
        response = await self.hass.async_add_executor_job(partial(self.discovery.scan, packet_builder.scan(), ip, attempts=attempts))
        if response is None:
            return None
        facts = parse_scan_message(response)
        # Preserve discovery's identity rejection before the accepted-type check.
        if canonical_mac(facts[CONF_MAC]) != canonical_mac(expected_mac):
            raise DeviceIdentityMismatch
        return replace(device_config(facts), firmware_source="textual_scan", firmware_observed_at=datetime.now(UTC).isoformat())

    async def async_refresh_firmware(self, entry: ConfigEntry) -> SihasDeviceConfig | None:
        """One optional setup observation; persist only matching firmware evidence.

        Re-read entry facts after I/O, preserving concurrent rediscovery/user edits.
        A changed endpoint/identity invalidates this observation. Cancellation
        propagates and cannot publish metadata or construct a replacement runtime.
        Returns the accepted observation for display only, or None; its reported
        endpoint and CFG never replace configured facts.
        """
        before = device_config(entry.data)
        try:
            observed = await self.async_identify(before.ip, before.mac, attempts=1)
        except TimeoutError:
            _LOGGER.debug("Optional firmware observation: no_response_or_timeout")
            return
        except DeviceIdentityMismatch:
            _LOGGER.warning("Optional firmware observation: mac_mismatch")
            return
        except UnsupportedDeviceType:
            _LOGGER.warning("Optional firmware observation: family_mismatch")
            return
        except ValueError:
            _LOGGER.warning("Optional firmware observation: malformed_response")
            return
        except OSError:
            _LOGGER.warning("Optional firmware observation: transport_error")
            return
        except Exception:
            _LOGGER.warning("Optional firmware observation: acquisition_error")
            return
        if observed is None:
            _LOGGER.debug("Optional firmware observation: no_response_or_timeout")
            return
        current = device_config(entry.data)
        if observed.device_type != current.device_type:
            _LOGGER.warning("Optional firmware observation: family_mismatch")
            return
        if (current.mac, current.device_type, current.ip) != (before.mac, before.device_type, before.ip):
            _LOGGER.debug("Optional firmware observation: configuration_changed")
            return
        self.hass.config_entries.async_update_entry(entry, data={
            **entry.data, CONF_FIRMWARE: observed.firmware,
            "firmware_source": observed.firmware_source, "firmware_observed_at": observed.firmware_observed_at,
        })
        _LOGGER.debug("Optional firmware observation: accepted_observation")
        return observed

    def create_runtime(self, device: SihasDeviceConfig, entry: ConfigEntry | None,
                       observation: SihasDeviceConfig | None = None) -> SihasRuntime | None:
        """Compose one runtime from the family registration; the family prepares its semantics once.

        An identifier without evidenced semantics gets no runtime. An accepted setup
        `observation` is retained only as display identification.
        """
        family = FAMILIES[device.device_type]
        if family.prepare is None:
            return None
        client = SihasClient(self.hass, self.transport_factory(device.ip))
        binding = family.prepare(device.config, device.firmware)
        coordinator = SihasCoordinator(self.hass, entry, client, binding.resolve, family.poll_interval,
                                       first_refresh_retry=family.first_refresh_retry)
        identification = DeviceIdentification.of(observation, "scan") if observation is not None else DeviceIdentification.of(device, "config")
        return SihasRuntime(client, device, coordinator, binding, identification, family.entities)

    async def async_validate(self, device: SihasDeviceConfig) -> None:
        """Validate manual facts using the same refresh owner as entry setup.

        RCM has no evidenced decoder: accepting its identifier proves no active
        functionality. No poll or synthetic decoder is added for that identifier.
        A flow owns this transient coordinator and always shuts it down.
        """
        runtime = self.create_runtime(device, None)
        if runtime is None:
            return
        coordinator = runtime.coordinator
        try:
            await coordinator.async_refresh()
            if not coordinator.last_update_success:
                raise coordinator.last_exception
        finally:
            await coordinator.async_shutdown()


DATA_COMPOSITION: HassKey[SihasComposition] = HassKey("sihas_composition")


def get_composition(hass: HomeAssistant) -> SihasComposition:
    """Resolve shared production composition, including flows before entry setup."""
    if DATA_COMPOSITION not in hass.data:
        hass.data[DATA_COMPOSITION] = SihasComposition(hass)
    return hass.data[DATA_COMPOSITION]
