"""SiHAS wire-protocol constants: no Home Assistant policy belongs here."""

from typing import Final, List

ENDIAN: Final = "big"

DEVICE_TYPE: Final = {
    "WAP": 0,
    "RXM": 1,
    "TCM": 2,
    "OCM": 3,
    "STM": 4,
    "CCM": 5,
    "DCM": 6,
    "ACM": 7,
    "GCM": 8,
    "SDM": 9,
    "SCM": 10,
    "HCM": 11,
    "AQM": 12,
    "BCM": 13,
    "HVM": 14,
    "SGW": 15,
    "LCM": 16,
    "PMM": 17,
    "PIM": 18,
    "RBM": 19,
    "HGW": 20,
    "SBM": 21,
    "PCM": 22,
    "ISM": 23,
    "CGM": 24,
    "WCM": 25,
    "SHB": 26,
    "SQM": 27,
    "RCM": 28,
    "HQM": 29,
}

SUPPORT_DEVICE: Final[List[str]] = [
    "ACM",
    "AQM",
    "BCM",
    "CCM",
    "HCM",
    "HVM",
    "PMM",
    "RBM",
    "SBM",
    "SDM",
    "SQM",
    "STM",
    "TCM",
    "RCM",
    "HQM",
]

DEFAULT_TIMEOUT: Final = 0.5
PORT: Final = 502
BUF_SIZE: Final = 1024

MAC_OUI: Final = "a82bd6"
