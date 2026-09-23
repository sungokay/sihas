"""Read-only AQM metadata; observed words never qualify commands or HA exposure."""
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Quality = Literal["valid", "unknown", "missing", "invalid"]


def is_word(value: int | None) -> bool:
    return type(value) is int and 0 <= value <= 65535


def _raw(registers: Sequence[int | None], index: int) -> int | None:
    return registers[index] if index < len(registers) else None


@dataclass(frozen=True)
class Hardware:
    raw: int | None
    revision: int | None
    vendor: str | None
    quality: Quality


@dataclass(frozen=True)
class SensorMask:
    raw: int | None
    temperature_humidity: bool | None
    co2: bool | None
    particulate: bool | None
    tvoc: bool | None
    illuminance: bool | None
    unknown_bits: int | None
    quality: Quality


@dataclass(frozen=True)
class AqmMetadata:
    config: int | None
    firmware: str | None
    display: Literal["lcd", "fnd"] | None
    hardware: Hardware
    sensor_mask: SensorMask

    @property
    def device_type(self) -> str:
        return "AQM"

    @property
    def evidence(self) -> str:
        """Interpretation source, not physical-profile qualification."""
        return "app_static"


def decode_metadata(registers: Sequence[int | None], *, config: int | None = None, firmware: str | None = None) -> AqmMetadata:
    """Keep configured facts independent from mutable R8/R9 read observations.

    Only config 1 (app FND branch) and 2 (documented LCD example) are named.
    Unlisted configs stay unknown instead of following the app's catch-all LCD
    branch. R9 flags report bits, not physical support or entity availability.
    Missing/invalid words retain raw input but never produce invented values.
    """
    r8, r9 = _raw(registers, 8), _raw(registers, 9)
    if is_word(r8):
        vendor = {1: "sensirion", 2: "renesas_tempus"}.get(r8)
        hardware = Hardware(r8, r8, vendor, "valid" if vendor is not None else "unknown")
    else:
        hardware = Hardware(r8, None, None, "missing" if r8 is None else "invalid")
    if is_word(r9):
        unknown = r9 & 0xFFE0
        mask = SensorMask(r9, *(bool(r9 & (1 << bit)) for bit in range(5)), unknown, "unknown" if unknown else "valid")
    else:
        mask = SensorMask(r9, None, None, None, None, None, None, "missing" if r9 is None else "invalid")
    display = {1: "fnd", 2: "lcd"}.get(config) if type(config) is int else None
    return AqmMetadata(config, firmware, display, hardware, mask)
