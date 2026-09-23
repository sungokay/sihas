"""Shared configured facts and executor-safe discovery/runtime composition.

One HA-instance service supplies discovery and register transports to workflows.
The transports are normal composition contracts: textual discovery is deliberately
separate from the register client's DatagramTransport. Neither validates new
capabilities or interprets additional device semantics.
"""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, UTC
from functools import partial
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .client import SihasClient
from .const import CONF_CFG, CONF_FIRMWARE, CONF_IP, CONF_MAC, CONF_NAME, CONF_TYPE
from .coordinator import SihasCoordinator
from .devices.state import definition_resolver, state_decoder
from .protocol.const import SUPPORT_DEVICE
from .protocol.packet import packet_builder
from .runtime import SihasDeviceConfig, SihasRuntime
from .protocol.discovery import DiscoveryTransport, UdpDiscoveryTransport
from .protocol.transport import DatagramTransport, UdpTransport
from .util import canonical_mac, parse_scan_message


_LOGGER = logging.getLogger(__name__)


class UnsupportedDeviceType(ValueError):
    """The configured type is outside the existing accepted identifier list."""


class DeviceIdentityMismatch(ValueError):
    """The scan's canonical MAC does not match the discovered physical device."""


def device_config(data: Mapping[str, Any]) -> SihasDeviceConfig:
    """Normalize existing configured facts without discovering capabilities."""
    mac = canonical_mac(data[CONF_MAC])
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        raise ValueError("Invalid MAC address")
    family = data[CONF_TYPE]
    if family not in SUPPORT_DEVICE:
        raise UnsupportedDeviceType(family)
    ip, config, name = data[CONF_IP], data[CONF_CFG], data.get(CONF_NAME, "")
    if not isinstance(ip, str) or not ip or type(config) is not int or not isinstance(name, str):
        raise ValueError("Invalid configured facts")
    firmware = data.get(CONF_FIRMWARE)
    if firmware is not None and not isinstance(firmware, str):
        raise ValueError("Invalid firmware metadata")
    source, observed_at = firmware_provenance(firmware, data.get("firmware_source"), data.get("firmware_observed_at"))
    return SihasDeviceConfig(ip, mac, family, config, name, firmware, source, observed_at)


def firmware_provenance(firmware: str | None, source: str | None = None, observed_at: str | None = None) -> tuple[str, str | None]:
    """Validate optional observation provenance without guessing a legacy date."""
    if firmware is None:
        return "missing", None
    if source == "textual_scan":
        try:
            timestamp = datetime.fromisoformat(observed_at)
            if timestamp.utcoffset() == timedelta(0):
                return "textual_scan", timestamp.isoformat()
        except (TypeError, ValueError):
            pass
    return "legacy_stored", None


def config_data(device: SihasDeviceConfig) -> dict[str, Any]:
    """Keep configured facts, preserving optional observed firmware without guessing."""
    data = {CONF_IP: device.ip, CONF_MAC: device.mac, CONF_TYPE: device.device_type,
            CONF_CFG: device.config, CONF_NAME: device.name}
    if device.firmware is not None:
        data[CONF_FIRMWARE] = device.firmware
        if device.firmware_source == "textual_scan" and device.firmware_observed_at is not None:
            data["firmware_source"] = device.firmware_source
            data["firmware_observed_at"] = device.firmware_observed_at
    return data


class SihasValidation:
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

    async def async_refresh_firmware(self, entry: ConfigEntry) -> None:
        """One optional setup observation; persist only matching firmware evidence.

        Re-read entry facts after I/O, preserving concurrent rediscovery/user edits.
        A changed endpoint/identity invalidates this observation. Cancellation
        propagates and cannot publish metadata or construct a replacement runtime.
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

    def create_runtime(self, device: SihasDeviceConfig, entry: ConfigEntry | None) -> SihasRuntime:
        client = SihasClient(self.hass, self.transport_factory(device.ip))
        decoder = state_decoder(device.device_type, device.config, firmware=device.firmware)
        coordinator = (
            SihasCoordinator(
                self.hass, entry, client, decoder,
                timedelta(seconds=10 if device.device_type in ("AQM", "PMM") else 5),
                first_refresh_retry=1 if device.device_type in ("HCM", "HVM") else 3,
                definition_resolver=definition_resolver(device.device_type, device.config, firmware=device.firmware),
            ) if decoder is not None else None
        )
        return SihasRuntime(client, device, coordinator)

    async def async_validate(self, device: SihasDeviceConfig) -> None:
        """Validate manual facts using the same refresh owner as entry setup.

        RCM has no evidenced decoder: accepting its identifier proves no active
        functionality. No poll or synthetic decoder is added for that identifier.
        A flow owns this transient coordinator and always shuts it down.
        """
        coordinator = self.create_runtime(device, None).coordinator
        if coordinator is None:
            return
        try:
            await coordinator.async_refresh()
            if not coordinator.last_update_success:
                raise coordinator.last_exception
        finally:
            await coordinator.async_shutdown()


DATA_VALIDATION: HassKey[SihasValidation] = HassKey("sihas_validation")


def get_validation(hass: HomeAssistant) -> SihasValidation:
    """Resolve shared production composition, including flows before entry setup."""
    if DATA_VALIDATION not in hass.data:
        hass.data[DATA_VALIDATION] = SihasValidation(hass)
    return hass.data[DATA_VALIDATION]
