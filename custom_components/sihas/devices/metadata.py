"""Neutral device-information display contract shared by family metadata callables."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceMetadata:
    """Optional display values; `None` keeps the common default for that field.

    A family returns only the fields it identifies from its already decoded state.
    These values are presentation only: no capability, decoding or command decision
    reads them, and they never replace device identity.
    """

    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None


MetadataReader = Callable[[Any], DeviceMetadata]
"""Family-owned callable reading a decoded snapshot state into display overrides."""
