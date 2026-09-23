"""HVM capture-time interpretation; no collection, lifecycle or device I/O."""
from dataclasses import fields, is_dataclass
from decimal import Decimal
import re
from typing import Any

from . import observation, schedule, summary

# These computed meanings belong to the existing codecs, not the JSON consumer.
_PROPERTIES = {
    observation.Temperature: ("celsius",),
    observation.Limits: ("status",),
    observation.Settings: ("scope",),
    observation.Summary: ("quality", "powered", "valve_open", "mode", "current_code", "target_code",
                          "current_temperature", "target_temperature"),
    schedule.SlotSetting: ("mode", "preserve_value", "temperature_celsius", "time_minutes"),
}


def _project(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)  # Exact decimal text; no float or context-dependent rounding.
    if is_dataclass(value) and not isinstance(value, type):
        result = {field.name: _project(getattr(value, field.name)) for field in fields(value)}
        result.update({name: _project(getattr(value, name)) for name in _PROPERTIES.get(type(value), ())})
        return result
    if isinstance(value, (tuple, list)):
        return [_project(item) for item in value]
    return value


def firmware_context(firmware: str | None) -> dict[str, Any]:
    """Parse only recorded dotted integer components, never a numeric approximation."""
    match = re.fullmatch(r"V?([0-9]{1,2})\.([0-9]{1,3})", firmware) if isinstance(firmware, str) else None
    version = (int(match[1]), int(match[2])) if match else None
    return {"raw": firmware, "source": "configured_firmware" if firmware is not None else "absent",
            "components": list(version) if version is not None else None,
            "quality": "missing" if firmware is None else "valid" if version is not None else "unknown",
            "schedule_layout": "app_static" if schedule.supports_firmware(version) else "unqualified"}


def _pair_quality(raw, version) -> str:
    if any(word is not None and (type(word) is not int or not 0 <= word <= 65535) for word in raw):
        return "invalid"
    if any(word is None for word in raw):
        return "missing"
    return "valid" if schedule.supports_firmware(version) else "unknown"


def decode_diagnostics(registers: tuple[int, ...], firmware: str | None) -> dict[str, Any]:
    """Project all existing HVM readers from one immutable input with local failures.

    Quality describes interpretation only. Settings/schedule scope and physical
    acceptance remain unresolved even when every wire word decodes successfully.
    """
    context = firmware_context(firmware)
    version = tuple(context["components"]) if context["components"] is not None else None
    result: dict[str, Any] = {"decoder": __name__, "projection_schema_version": 1, "firmware": context,
                              "interpretation": "capture_time_app_static_not_physical_acceptance",
                              "temperature_unit": "°C", "exact_decimals": "decimal strings",
                              "settings_and_schedule_scope": "unresolved", "errors": []}

    def section(name, producer):
        try:
            result[name] = producer()
        except Exception:
            # Exception messages may contain raw user/device data. Never export repr.
            result[name] = {"status": "failed"}
            result["errors"].append({"stage": "decode", "path": f"decoded.{name}", "description": "HVM interpretation failed"})

    try:
        observed = observation.decode(registers)
    except Exception:
        observed = None
    references = {
        "profile": {"heating_type": 20, "room_count": 21, "homenet": 22, "sez": 26, "rs485_id": 27, "summary_unit": 59},
        "detail": {"selected_room": 10, "power": 0, "target": 1, "mode": 2, "current": 3, "valve": 4, "alarm": 5, "on_minutes": 9},
        "settings": {"display": 6, "backlight": 7, "compensation": 8, "away": 11, "upper": 12, "lower": 13, "deadband": 14},
        "rf": {"state": 15, "error": 18},
        "boiler_raw": [23, 24, 25, 60, 61, 62],
        "unknown_raw": [16, 17, 19, 63],
    }
    for name, addresses in references.items():
        section(name, lambda name=name, addresses=addresses: {"registers": addresses, "values": _project(getattr(observed, name))})

    def strict_summaries():
        return [{"register": 52 + index, "position": index + 1,
                 "within_current_room_count": (index < observed.profile.room_count.value
                                               if observed.profile.room_count.value is not None else None),
                 **_project(item)} for index, item in enumerate(observed.summaries)]

    section("strict_summaries", strict_summaries)
    section("production_compatible_summaries", lambda: {
        "interpretation": "legacy_nonzero_R59_half_degree_fallback", "register_start": 52,
        "values": _project(summary.decode(registers)),
    })

    def slots():
        return [{"slot_index": index, "registers": [30 + index * 2, 31 + index * 2],
                 "quality": _pair_quality(item.raw, version), **_project(item)}
                for index, item in enumerate(schedule.decode_slots(registers, version))]

    def periodic():
        return [{"bank_index": index, "registers": addresses, "quality": _pair_quality(item.raw, version),
                 "temperature_unit": "°C", "end_action_scope": "end_of_whole_interval", **_project(item)}
                for index, (addresses, item) in enumerate(zip(([50, 51], [28, 29]), schedule.decode_periodic_banks(registers, version)))]

    section("general_schedule", slots)
    section("periodic_banks", periodic)
    return result
