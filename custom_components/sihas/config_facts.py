"""Configured device facts: normalization and optional firmware provenance; no I/O."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
import re
from typing import Any

from .const import CONF_CFG, CONF_FIRMWARE, CONF_IP, CONF_MAC, CONF_NAME, CONF_SSID, CONF_TYPE
from .protocol.const import SUPPORT_DEVICE
from .protocol.multi_control import SSID_LENGTH
from .runtime import SihasDeviceConfig
from .util import canonical_mac


class UnsupportedDeviceType(ValueError):
    """The configured type is outside the existing accepted identifier list."""


class InvalidSsid(ValueError):
    """The configured SSID is not text of at most 32 UTF-8 bytes."""


def normalize_ssid(value: Any) -> str | None:
    """The device network SSID, case-sensitive and unmodified; missing or empty means not configured."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.encode("utf-8")) > SSID_LENGTH:
        raise InvalidSsid(f"SSID must be text of at most {SSID_LENGTH} UTF-8 bytes")
    return value


def default_name(device: SihasDeviceConfig) -> str:
    """Device-derived name and title for a new entry: the family followed by the canonical MAC."""
    return device.device_type + device.mac


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
    return SihasDeviceConfig(ip, mac, family, config, name, firmware, source, observed_at, normalize_ssid(data.get(CONF_SSID)))


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
    if device.ssid is not None:
        data[CONF_SSID] = device.ssid
    return data
