"""Textual SiHAS identification parsing and IP wire-format normalization.

The returned MAC is the wire-format text exactly as matched, never canonicalized:
Home Assistant's own MAC canonicalization policy is applied by callers outside
this boundary, keeping that identity policy out of the protocol layer.
"""
from ipaddress import IPv4Address
import re
from typing import Dict


class IpConv:
    @staticmethod
    def remove_leading_zero(s: str) -> str:
        return re.sub(r"\b0+(\d)", r"\1", s)


_SCAN_RESPONSE = re.compile(
    r"SiHAS_(?P<family>[A-Z]{3})_V(?P<firmware>[^\s]{5}) "
    r"MAC=(?P<mac>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) "
    r"IP=(?P<ip>[0-9]{3}(?:\.[0-9]{3}){3}) CFG=(?P<cfg>[0-9A-Fa-f]{2})"
)


def parse_scan_message(msg: str) -> Dict:
    """Validate the evidenced textual response and preserve its exact firmware text.

    Named fields follow validated delimiters/widths, never independent offsets.
    Version interpretation belongs to each family, not this acquisition boundary.
    """
    match = _SCAN_RESPONSE.fullmatch(msg) if isinstance(msg, str) else None
    if match is None:
        raise ValueError("Malformed textual identification")
    return {
        "type": match["family"],
        "mac": match["mac"],
        "ip": str(IPv4Address(IpConv.remove_leading_zero(match["ip"]))),
        "cfg": int(match["cfg"], 16),
        "firmware": match["firmware"],
    }
