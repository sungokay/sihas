"""Passive AQM capture-time interpretation and evidenced linked-identity privacy."""
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from ...diagnostics_export import SensitiveField
from . import definition, link, metadata, settings, state

SENSITIVE_FIELDS = (SensitiveField(
    55, 58,
    (("decoded", "selected_link", "values", "bank_raw", 4),
     ("decoded", "selected_link", "values", "bank_raw", 5),
     ("decoded", "selected_link", "values", "bank_raw", 6),
     ("decoded", "selected_link", "values", "bank", "mac")),
    "linked_target_mac", "AQM_protocol_R55_R57",
),)

_PROPERTIES = {
    metadata.AqmMetadata: ("device_type", "evidence"),
    settings.ThresholdTriplet: ("ordered",),
    link.SelectedLink: ("selector_quality", "selected_index", "bank", "enabled_rules", "unknown_enable_bits"),
    link.LinkBank: ("condition",),
    link.Event: ("event_type", "period_code", "period_seconds"),
    link.Condition: ("value",),
    link.Notifications: ("push", "lamp", "sound", "repeat"),
    link.TimeCondition: ("mode", "repeat", "weekday_or_date", "begin_hour", "begin_minute", "end_hour", "end_minute", "enabled", "words"),
}


def _project(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return {"value": value.value, "meaning": value.name}
    if isinstance(value, bytes):
        return value.hex(":")
    if is_dataclass(value) and not isinstance(value, type):
        result = {field.name: _project(getattr(value, field.name)) for field in fields(value)}
        result.update({name: _project(getattr(value, name)) for name in _PROPERTIES.get(type(value), ())})
        if isinstance(value, metadata.AqmMetadata):
            # One firmware text export boundary, shared with common provenance.
            result.pop("firmware")
            result["firmware_reference"] = "decoded.firmware"
        return result
    if isinstance(value, (tuple, list)):
        return [_project(item) for item in value]
    return value


def decode_diagnostics(registers: tuple[int, ...], prepared: definition.Prepared) -> dict[str, Any]:
    """Read existing owners from one tuple with the runtime's configured facts; never select another bank or perform I/O."""
    config, firmware = prepared.config, prepared.firmware
    result: dict[str, Any] = {
        "decoder": __name__, "projection_schema_version": 1,
        "interpretation": "capture_time_app_static_not_physical_acceptance",
        "firmware": {"raw": firmware, "source": "configured_firmware" if firmware is not None else "absent",
                     "quality": "missing" if firmware is None else "recorded_text", "version_interpretation": "not_inferred"},
        "errors": [],
        "not_collected": {"other_link_banks": "passive_current_window_only", "trend_history": "not_in_normal_register_capture",
                          "remote_latest_firmware": "not_queried", "action_completion": "not_exercised"},
    }

    def section(name, addresses, producer):
        try:
            result[name] = {"registers": addresses, "values": _project(producer())}
        except Exception:
            result[name] = {"status": "failed"}
            result["errors"].append({"stage": "decode", "path": f"decoded.{name}", "description": "AQM interpretation failed"})

    def measurements():
        observed = state.decode_aqm(registers, config=config, firmware=firmware)
        return {name: {"value": getattr(observed, name), "unit": unit} for name, unit in (
            ("temperature", "°C"), ("humidity", "%"), ("co2", "ppm"), ("pm25", "µg/m³"),
            ("pm10", "µg/m³"), ("tvoc", "ppb"), ("illuminance", "lx"))}

    section("measurements", list(range(7)), measurements)
    section("metadata", [8, 9], lambda: metadata.decode_metadata(registers, config=config, firmware=firmware))
    section("settings", [*range(10, 26), 27, 28, 29], lambda: settings.decode_settings(
        registers, display=metadata.decode_metadata(registers, config=config, firmware=firmware).display))
    section("selected_link", list(range(50, 63)), lambda: link.decode_selected_link(registers))
    return result
