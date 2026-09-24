"""Copy-only privacy and JSON export for SiHAS diagnostic evidence."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import math
import re
from typing import Any

_REDACTED = "**REDACTED**"
_PRIVATE_KEY = re.compile(r"password|passwd|secret|token|api.?key|credential|^mac$|mac_address|ip_address|^ip$|^host$|^hostname$|^address$|"
                          r"latitude|longitude|location|person|username|email|ssid|serial|friendly_name|^name$|^title$", re.I)
_TEXT_IDENTIFIERS = re.compile(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}|"
                               r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_SECRET_TEXT = re.compile(r"(?:password|passwd|token|api[_-]?key|secret)\s*[=:]\s*[^\s\x00,;}]+", re.I)
# HA presentation attributes needed to compare current states with the read.
_ENTITY_ATTRIBUTES = frozenset({
    "attribution", "type", "device_class", "state_class", "unit_of_measurement", "icon", "supported_features",
    "temperature", "current_temperature", "target_temp_high", "target_temp_low", "min_temp", "max_temp", "target_temp_step",
    "hvac_modes", "hvac_action", "fan_mode", "fan_modes", "preset_mode", "preset_modes", "swing_mode", "swing_modes",
    "humidity", "current_humidity", "brightness", "color_mode", "supported_color_modes", "assumed_state",
    "options", "current_position", "position", "mode", "available",
})


@dataclass(frozen=True)
class SensitiveField:
    """Family-evidenced R[start:end] and exact decoded alias paths (end exclusive)."""

    start: int
    end: int
    aliases: tuple[tuple[str | int, ...], ...]
    reason: str
    provenance: str


class DiagnosticExport:
    """Request-local, copy-only export with explicit text and binary provenance."""

    def __init__(self, config: Mapping, options: Mapping, *, title: str = "", private_values: Sequence[Mapping] = ()) -> None:
        self.redactions: list[dict[str, Any]] = []
        self.errors: list[dict[str, str]] = []
        self._private: set[str] = set()
        for source in (config, options):
            for key, value in source.items():
                if key not in {"type", "cfg", "firmware", "firmware_source", "firmware_observed_at"}:
                    self._remember(value)
        self._remember(title)
        for attributes in private_values:
            for key, value in attributes.items():
                if key not in _ENTITY_ATTRIBUTES or _PRIVATE_KEY.search(key):
                    self._remember(value)

    def _remember(self, value: Any, depth: int = 0) -> None:
        if depth > 32:
            return
        if isinstance(value, str) and value:
            self._private.add(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                self._remember(item, depth + 1)
        elif isinstance(value, (tuple, list)):
            for item in value:
                self._remember(item, depth + 1)

    def _text(self, value: str, *, private_context: bool = True) -> str:
        if private_context and self._private:
            pattern = "|".join(re.escape(private) for private in sorted(self._private, key=len, reverse=True))
            value = re.sub(pattern, lambda match: _REDACTED, value)
        return _SECRET_TEXT.sub(_REDACTED, _TEXT_IDENTIFIERS.sub(_REDACTED, value))

    def entity_state(self, value: str, path: str, *, generated: bool) -> str:
        """Generated state ignores arbitrary context; bounded private syntax still applies."""
        safe = self._text(value, private_context=not generated)
        if safe != value:
            self._note(path, "private_text")
        return safe

    def _note(self, path: str, reason: str, **details) -> None:
        self.redactions.append({"path": path, "reason": reason, "provenance": "field_ownership", **details})

    def payload(self, payload: bytes, path: str, *, sensitive: Sequence[SensitiveField] = ()) -> dict[str, Any]:
        """Zero only evidenced field ranges or bounded, unmistakable textual material.

        Configured names/secrets are never binary needles. UTF-16 text is checked
        only for identifier/credential syntax, at both alignments and byte orders.
        The caller supplies family ranges only for received register packets.
        """
        ranges = []
        for field in sensitive:
            start, end = 9 + field.start * 2, min(len(payload), 9 + field.end * 2)
            if start < end:
                ranges.append((start, end, field.reason, field.provenance))
        representations = [(payload.decode("latin-1"), 0, 1)]
        for offset in (0, 1):
            even = payload[offset:len(payload) - ((len(payload) - offset) % 2)]
            for order in ("big", "little"):
                # Keep surrogate code units separate so offsets remain exact.
                text = "".join(chr(int.from_bytes(even[index:index + 2], order)) for index in range(0, len(even), 2))
                representations.append((text, offset, 2))
        for text, offset, width in representations:
            for pattern in (_TEXT_IDENTIFIERS, _SECRET_TEXT):
                for match in pattern.finditer(text):
                    ranges.append((offset + width * match.start(), offset + width * match.end(),
                                   "textual_private_material", "bounded_text_identifier_or_credential"))
        safe = bytearray(payload)
        for start, end, reason, provenance in sorted(set(ranges)):
            safe[start:end] = bytes(end - start)
            self._note(path, reason, byte_range=[start, end], range_convention="zero_based_end_exclusive",
                       replacement="zero bytes", provenance=provenance)
        return {"hex": safe.hex(), "length": len(payload), "original": not ranges}

    def protect_fields(self, result: dict, sensitive: Sequence[SensitiveField]) -> None:
        """Apply family aliases and register ranges to already isolated export copies."""
        for field in sensitive:
            if result.get("registers"):
                for address in range(field.start, field.end):
                    result["registers"]["values"][address] = _REDACTED
                self._note("registers.values", field.reason, register_range=[field.start, field.end],
                           range_convention="zero_based_end_exclusive", provenance=field.provenance)
            for alias in field.aliases:
                node = result
                try:
                    for part in alias[:-1]:
                        node = node[part]
                    node[alias[-1]] = _REDACTED
                except (KeyError, IndexError, TypeError):
                    continue  # A failed/missing section has no alias to disclose.
                self._note(".".join(map(str, alias)), field.reason, provenance=field.provenance)

    def protect_text_projections(self, result: dict, addresses: set[int]) -> None:
        """Retain safe sections; withhold only projections overlapping textual bytes.

        Register references are supplied by family projections. An unreferenced
        structured projection is uncertain, so only that section is withheld.
        """
        if not addresses or not result.get("registers"):
            return
        for address in sorted(addresses):
            result["registers"]["values"][address] = _REDACTED
            self._note(f"registers.values[{address}]", "textual_private_material", provenance="received_byte_range")

        def visit(value, path):
            if isinstance(value, list):
                return [visit(item, f"{path}[{index}]") for index, item in enumerate(value)]
            if not isinstance(value, dict):
                return value
            refs = value.get("registers", value.get("register"))
            if isinstance(refs, dict):
                refs = list(refs.values())
            if type(refs) is int:
                refs = [refs]
            if refs is None and "register_start" in value:
                refs = range(value["register_start"], 64)
            if refs is not None and not addresses.intersection(refs):
                return value
            self._note(path, "affected_or_uncorrelated_text_projection", provenance="received_byte_range")
            return {"status": "unavailable", "reason": "private_response_bytes"}

        if isinstance(result.get("decoded"), dict):
            for key, value in result["decoded"].items():
                if key not in {"firmware", "errors"}:
                    result["decoded"][key] = visit(value, f"decoded.{key}")

    def entity_attributes(self, attributes: Mapping, path: str, *, generated: frozenset[str] = frozenset()) -> dict:
        """Allowlisted presentation attributes plus producer-proven generated ones.

        Generated values ignore arbitrary private context but still receive the
        bounded identifier/credential syntax check; private key names never pass.
        """
        result = {}
        for key, value in attributes.items():
            if _PRIVATE_KEY.search(key):
                self._note(f"{path}.<excluded_attribute>", "attribute_outside_diagnostic_allowlist")
            elif key in generated:
                result[key] = self._generated(value, f"{path}.{key}")
            elif key in _ENTITY_ATTRIBUTES:
                result[key] = value
            else:
                self._note(f"{path}.<excluded_attribute>", "attribute_outside_diagnostic_allowlist")
        return result

    def _generated(self, value: Any, path: str, depth: int = 0) -> Any:
        if depth > 32:
            return self._unavailable(path)
        if isinstance(value, str):
            safe = self._text(value, private_context=False)
            if safe != value:
                self._note(path, "private_text")
            return safe
        if isinstance(value, (list, tuple)):
            return [self._generated(item, f"{path}[{index}]", depth + 1) for index, item in enumerate(value)]
        if isinstance(value, Mapping):
            return {key: self._generated(item, f"{path}.{key}", depth + 1) for key, item in value.items() if isinstance(key, str)}
        return value

    def copy(self, value: Any, path: str = "data", *, generated: bool = False, _depth: int = 0) -> Any:
        """Isolate a bad leaf without unsafe repr or discarding the download."""
        if _depth > 32:
            return self._unavailable(path)
        if isinstance(value, Enum):
            return self.copy(value.value, path, generated=generated, _depth=_depth + 1)
        if value is None or type(value) in (bool, int):
            return value
        if isinstance(value, str):
            safe = value if generated else self._text(value)
            if safe != value:
                self._note(path, "private_text")
            return safe
        if type(value) is float and math.isfinite(value):
            return value
        if isinstance(value, Decimal) and value.is_finite():
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    self._unavailable(path + ".<non_string_key>")
                    continue
                safe_key = key if generated else self._text(key)
                item_path = f"{path}.{safe_key}"
                if _PRIVATE_KEY.search(key):
                    result[safe_key] = _REDACTED
                    self._note(item_path, "private_field")
                else:
                    result[safe_key] = self.copy(item, item_path, generated=generated, _depth=_depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [self.copy(item, f"{path}[{index}]", generated=generated, _depth=_depth + 1) for index, item in enumerate(value)]
        return self._unavailable(path)

    def _unavailable(self, path: str) -> dict[str, str]:
        self.errors.append({"stage": "serialization", "path": path, "description": "Unsupported JSON value omitted"})
        return {"status": "unavailable"}
