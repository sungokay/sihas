from typing import Dict

from homeassistant.helpers.device_registry import format_mac

from .protocol.identification import parse_scan_message as _parse_scan_message


def canonical_mac(mac: str) -> str:
    """Return the single canonical SiHAS physical-device MAC address.

    Delegates to Home Assistant's own `format_mac()` so every discovery path,
    config entry, runtime device object, and DeviceInfo stays in sync with the
    Device Registry's own MAC canonicalization rule.
    """
    return format_mac(mac)


def parse_scan_message(msg: str) -> Dict:
    """Parse the evidenced textual response and canonicalize its MAC identity.

    Structural parsing is HA-independent protocol logic; MAC canonicalization is
    Home Assistant's own identity policy, applied here at the HA/runtime boundary.
    """
    facts = _parse_scan_message(msg)
    return {**facts, "mac": canonical_mac(facts["mac"])}
