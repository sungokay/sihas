"""BCM capture-time projection of existing read owners; no device I/O."""
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from . import definition, schedule, settings, state

_PROPERTIES = {
    state.BcmIdentity: ("evidence",),
    state.BcmRange: ("minimum", "maximum"),
    state.BcmHotWaterRange: ("minimum", "maximum", "levels"),
    state.BcmLimits: ("hot_water_kind",),
    state.BcmTimerValidation: ("period_upper_hours", "run_minute_step"),
    state.BcmOperation: ("hot_water", "heating", "ondol", "bath", "unknown_bits"),
    settings.Compensation: ("value", "within_guide"),
    schedule.NewSetting: ("preserve_value",),
}


def _project(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return {"value": value.value, "meaning": value.name}
    if is_dataclass(value) and not isinstance(value, type):
        result = {field.name: _project(getattr(value, field.name)) for field in fields(value)}
        result.update({name: _project(getattr(value, name)) for name in _PROPERTIES.get(type(value), ())})
        return result
    if isinstance(value, (tuple, list)):
        return [_project(item) for item in value]
    return value


def firmware_context(prepared: definition.Prepared) -> dict[str, Any]:
    """Export the runtime's prepared firmware choices; the text is not parsed again."""
    firmware, version = prepared.firmware, prepared.version
    return {"raw": firmware, "source": "configured_firmware" if firmware is not None else "absent",
            "components": list(version) if version is not None else None,
            "quality": "missing" if firmware is None else "valid" if version is not None else "unknown",
            "schedule_layout": prepared.schedule_layout}


def decode_diagnostics(registers: tuple[int, ...], prepared: definition.Prepared) -> dict[str, Any]:
    """Project the identical capture through the runtime's prepared BCM semantics, retaining local failures.

    The capture's own R15/R16 select its definition; readers whose meaning depends
    on that selection are taken from its decoded state.
    """
    result: dict[str, Any] = {"decoder": __name__, "projection_schema_version": 1, "firmware": firmware_context(prepared),
                              "interpretation": "capture_time_app_static_not_physical_acceptance",
                              "temperature_unit": "°C", "exact_decimals": "decimal strings", "errors": []}

    def section(name, addresses, producer):
        try:
            result[name] = {"registers": addresses, "values": _project(producer())}
        except Exception:
            result[name] = {"status": "failed"}
            result["errors"].append({"stage": "decode", "path": f"decoded.{name}", "description": "BCM interpretation failed"})

    try:
        # Resolve from this capture, never from the coordinator's prior definition.
        observed = definition.decode(registers, prepared)
    except Exception:
        observed = None

    section("state", list(range(17)), lambda: {
        name: _project(getattr(observed, name)) for name in (
            "powered", "preset", "program", "program_raw", "burner", "action", "current_temperature", "target",
            "room_target", "ondol_target", "manufacturer", "problem", "connected", "water_status")
    })
    section("climate_words", [1, 2, 8, 9, 11, 12, 13, 14], lambda: {
        "room_target_celsius": registers[1], "ondol_target_celsius": registers[2], "room_current_tenths": registers[8],
        "ondol_current_celsius": registers[9], "fire_raw": registers[11], "error_raw": registers[12],
        "water_raw": registers[13], "connectivity_raw": registers[14],
    })
    section("identity", [15, 16], lambda: state.identify(registers))
    section("limits", [15, 16, 21, 22, 23, 24, 25, 26], lambda: observed.limits)
    section("timer_validation", [15, 16, 28], lambda: observed.timer_validation)
    section("hot_water", [3, 15, 16, 21, 22], lambda: observed.hot_water)
    section("hot_water_temperature", [10, 15, 16, 21, 22], lambda: observed.hot_water_temperature)
    section("timer", [7, 15, 16, 28], lambda: observed.timer)
    section("operation_flags", [4], lambda: state.decode_operation(registers[4]))
    section("heating_level", [15, 16, 29], lambda: observed.heating_level)
    section("settings", [17, 18, 52, 62], lambda: settings.decode_settings(registers))

    def slots():
        output = []
        for index, slot in enumerate(observed.schedule_slots):
            quality = ("missing" if None in slot.raw else "invalid") if slot.time is None else (
                "valid" if slot.setting is not None else "unknown")
            item = {"slot_index": index, "registers": [30 + index * 2, 31 + index * 2], "quality": quality, **_project(slot)}
            if isinstance(slot.setting, schedule.NewSetting):
                if slot.setting.mode == "timer":
                    item["timer_period_hours_run_minutes"] = _project(schedule.decode_timer_parameter(slot.setting.parameter))
                elif slot.setting.mode == "hot_water":
                    item["hot_water_level"] = schedule.decode_hot_water_level(slot.setting.parameter, observed.limits.hot_water)
                elif slot.setting.mode in ("room", "ondol"):
                    item["temperature_unit"] = "°C"
            output.append(item)
        return output

    try:
        result["general_schedule"] = slots()
    except Exception:
        result["general_schedule"] = {"status": "failed"}
        result["errors"].append({"stage": "decode", "path": "decoded.general_schedule", "description": "BCM schedule interpretation failed"})
    section("interval", [50, 51], lambda: schedule.decode_interval(registers[50], registers[51]))
    return result
