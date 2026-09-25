"""Standard HA Diagnostics: request-local SiHAS collection and family routing."""
from collections.abc import Callable
from datetime import datetime, UTC
import re
from typing import Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .devices.hvm.diagnostics import decode_diagnostics as decode_hvm
from .devices.bcm.diagnostics import decode_diagnostics as decode_bcm
from .devices.aqm.diagnostics import decode_diagnostics as decode_aqm, SENSITIVE_FIELDS as AQM_SENSITIVE_FIELDS
from .diagnostics_export import DiagnosticExport, SensitiveField
from .entity import SihasProjection
from .errors import ModbusNotEnabledError, PacketSizeError
from .runtime import SihasConfigEntry
from .trace import ExchangeTrace
from .validation import firmware_provenance


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _produced_attributes(producer: SihasProjection) -> dict[str, Any]:
    """The loaded producer's own current HA attribute output, composed as HA composes state attributes."""
    try:
        return {**(producer.capability_attributes or {}), **(producer.state_attributes or {}), **(producer.extra_state_attributes or {})}
    except Exception:
        return {}


def _generated_attributes(producer: SihasProjection | None, attributes: dict[str, Any]) -> frozenset[str]:
    """Declared producer attributes whose sampled value equals the producer's current output.

    Unknown, externally replaced or changed values stay on the protected path.
    """
    if producer is None or not producer.diagnostic_generated_attributes:
        return frozenset()
    produced = _produced_attributes(producer)
    return frozenset(key for key in producer.diagnostic_generated_attributes
                     if key in attributes and key in produced and attributes[key] == produced[key])


def _entities(hass: HomeAssistant, entry: SihasConfigEntry) -> dict[str, Any]:
    """Observe entry-owned HA states independently of any device publication."""
    runtime = getattr(entry, "runtime_data", None)
    mac = runtime.device.mac if runtime is not None else entry.unique_id
    device = next((item for item in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
                   if (DOMAIN, mac) in item.identifiers), None)
    # Confirm the sampled value against its loaded SiHAS producer. Unknown or
    # externally replaced free-form states retain private-context protection.
    producers = {entity.entity_id: entity for platform in async_get_platforms(hass, DOMAIN)
                 for entity in platform.entities.values() if isinstance(entity, SihasProjection) and entity.runtime is runtime}
    result = {"entities_collected_at": _now(), "sampling": "independent_HA_state_machine", "items": []}
    for registered in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if device is not None and registered.device_id not in (None, device.id):
            continue
        state = hass.states.get(registered.entity_id)
        item = {"entity_id": registered.entity_id, "present": state is not None,
                "disabled": registered.disabled_by is not None}
        if state is not None:
            producer = producers.get(registered.entity_id)
            item["_generated_state"] = producer is not None and (
                state.state in {"unknown", "unavailable"} or state.state == str(producer.state))
            item["_generated_attributes"] = _generated_attributes(producer, dict(state.attributes))
            item.update(state=state.state, attributes=dict(state.attributes), last_changed=state.last_changed,
                        last_updated=state.last_updated)
            if hasattr(state, "last_reported"):
                item["last_reported"] = state.last_reported
        result["items"].append(item)
    return result


async def _async_collect(hass: HomeAssistant, entry: SihasConfigEntry,
                         interpret: Callable[[tuple[int, ...], Any], dict] | None,
                         *, started: str, integration_version: str | None, sensitive: tuple[SensitiveField, ...] = ()) -> dict[str, Any]:
    """Common collection: fresh read, packets, registers, HA states and safe export.

    The family callable only interprets the same immutable register tuple with
    the runtime's prepared family choices. There is no setting/case selector,
    cached-success fallback or family-owned I/O.
    """
    config_data, options, title = entry.data, entry.options, entry.title
    runtime = getattr(entry, "runtime_data", None)
    device = runtime.device if runtime is not None else None
    firmware = device.firmware if device is not None else entry.data.get("firmware")
    firmware_source = (device.firmware_source if device is not None else entry.data.get("firmware_source"))
    firmware_observed_at = device.firmware_observed_at if device is not None else entry.data.get("firmware_observed_at")
    firmware_source, firmware_observed_at = firmware_provenance(firmware, firmware_source, firmware_observed_at)
    result: dict[str, Any] = {
        "capture": {"schema_version": 1, "request_id": str(uuid4()), "started_at": started, "ended_at": None,
                    "read_started_at": None, "read_finished_at": None, "outcome": "not_queried",
                    "integration_version": integration_version, "code_revision": None,
                    "decoder_provenance": "installed_integration", "evidence": "SiHAS_UDP_application_payloads"},
        "device": {"family": device.device_type if device is not None else entry.data.get("type"),
                   "configuration": device.config if device is not None else entry.data.get("cfg"),
                   "firmware": firmware, "firmware_source": firmware_source, "firmware_observed_at": firmware_observed_at,
                   "source": "loaded_configuration" if device is not None else "config_entry",
                   "model": None, "model_source": "not_recorded"},
        "exchange_trace": [], "registers": None, "decoded": None, "errors": [],
    }
    capture = result["capture"]
    events = ()
    if interpret is None:
        capture["outcome"] = "unsupported_family"
    elif runtime is None or runtime.commands is None:
        capture["outcome"] = "no_runtime"
    elif entry.state is not ConfigEntryState.LOADED:
        capture["outcome"] = "runtime_not_loaded"
    else:
        trace = ExchangeTrace()
        try:
            registers = await runtime.commands.async_diagnostic_read(trace)
        except (PacketSizeError, ModbusNotEnabledError):
            capture["outcome"] = "packet_failed"
            result["errors"].append({"stage": "packet", "description": "Existing response validation/extraction rejected the response"})
        except (TimeoutError, OSError):
            capture["outcome"] = "transport_failed"
            result["errors"].append({"stage": "transport", "description": "Device exchange failed; see per-attempt trace"})
        except Exception:
            capture["outcome"] = "read_failed"
            result["errors"].append({"stage": "read", "description": "Read admission or execution failed"})
        else:
            result["registers"] = {"address_convention": "zero_based_R0_through_R63", "values": registers}
            try:
                result["decoded"] = interpret(registers, runtime.binding.prepared)
                if "firmware" in result["decoded"]:
                    result["decoded"]["firmware"].update(source=firmware_source, observed_at=firmware_observed_at)
                result["errors"].extend(result["decoded"].get("errors", []))
            except Exception:
                result["errors"].append({"stage": "decode", "description": "Family interpretation failed"})
            capture["outcome"] = "partial" if result["errors"] else "success"
        # CancelledError deliberately propagates; the admission owner has drained
        # issued executor I/O before this collector can be discarded.
        try:
            events = trace.freeze()
        except RuntimeError:
            result["errors"].append({"stage": "trace", "description": "No completed exchange trace available"})
        if events:
            capture["read_started_at"] = events[0].timestamp
            capture["read_finished_at"] = events[-1].timestamp

    result["entities"] = _entities(hass, entry)
    # Values proven to be generated by the loaded producer are evidence, not private context.
    private_values = [{key: value for key, value in item.get("attributes", {}).items() if key not in item.get("_generated_attributes", ())}
                      for item in result["entities"]["items"]]
    if device is not None:
        private_values.append({"ip": device.ip, "mac": device.mac, "name": device.name})
    export = DiagnosticExport(config_data, options, title=title, private_values=private_values)
    for index, item in enumerate(result["entities"]["items"]):
        path = f"entities.items[{index}]"
        item["entity_id"] = export.copy(item["entity_id"], path + ".entity_id")
        generated_state = item.pop("_generated_state", False)
        generated_attributes = item.pop("_generated_attributes", frozenset())
        if "state" in item:
            numeric = re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", item["state"]) is not None
            item["state"] = export.entity_state(item["state"], path + ".state", generated=generated_state or numeric)
        if "attributes" in item:
            attributes = export.entity_attributes(item["attributes"], path + ".attributes", generated=generated_attributes)
            # Numeric/enum/unit attributes are HA presentation values. Only these
            # free-form presentation attributes may contain user/config text.
            for key in ({"attribution", "options", "fan_mode", "fan_modes", "preset_mode", "preset_modes"} & attributes.keys()) - generated_attributes:
                attributes[key] = export.copy(attributes[key], path + ".attributes." + key)
            item["attributes"] = attributes
    result = export.copy(result, generated=True)
    numeric_firmware = isinstance(firmware, str) and re.fullmatch(r"V?[0-9]+\.[0-9]+", firmware) is not None
    result["device"]["firmware"] = export.copy(firmware, "device.firmware", generated=numeric_firmware)
    if isinstance(result.get("decoded"), dict) and "firmware" in result["decoded"]:
        result["decoded"]["firmware"]["raw"] = export.copy(firmware, "decoded.firmware.raw", generated=numeric_firmware)
    textual_addresses: set[int] = set()
    for index, event in enumerate(events):
        item = {"attempt": event.attempt, "event": event.event, "timestamp": event.timestamp,
                "elapsed_seconds": event.elapsed_seconds, "error": event.error}
        if event.payload is not None:
            before = len(export.redactions)
            item["payload"] = export.payload(event.payload, f"exchange_trace[{index}].payload",
                                             sensitive=sensitive if event.event == "received" else ())
            if event.event == "received" and len(event.payload) == 137 and result.get("registers"):
                original = b"".join(word.to_bytes(2, "big") for word in result["registers"]["values"])
                if event.payload[9:] == original:
                    for note in export.redactions[before:]:
                        if note["reason"] == "textual_private_material":
                            start, end = note["byte_range"]
                            textual_addresses.update(range(max(0, (start - 9) // 2), min(64, (end - 9 + 1) // 2)))
        result["exchange_trace"].append(item)
    export.protect_fields(result, sensitive)
    export.protect_text_projections(result, textual_addresses)
    if textual_addresses:
        result["errors"].append({"stage": "privacy", "description": "Affected textual-byte projections withheld; safe evidence retained"})
        if result["capture"]["outcome"] == "success":
            result["capture"]["outcome"] = "partial"
    result["errors"].extend(export.errors)
    if export.errors and result["capture"]["outcome"] == "success":
        result["capture"]["outcome"] = "partial"
    result["redactions"] = export.redactions
    result["capture"]["ended_at"] = _now()
    return result


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SihasConfigEntry) -> dict[str, Any]:
    """Route supported interpretation without extending collection for each family."""
    started = _now()
    integration = await async_get_integration(hass, DOMAIN)
    # Resolve family/runtime after the only setup await, so a concurrent reload
    # cannot route a replacement family through an earlier interpretation choice.
    runtime = getattr(entry, "runtime_data", None)
    family = runtime.device.device_type if runtime is not None else entry.data.get("type")
    interpret = {"HVM": decode_hvm, "BCM": decode_bcm, "AQM": decode_aqm}.get(family)
    return await _async_collect(hass, entry, interpret,
                                started=started, integration_version=integration.version,
                                sensitive=AQM_SENSITIVE_FIELDS if family == "AQM" else ())
