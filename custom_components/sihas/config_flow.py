"""Workflow UX over shared configured facts and async-safe device validation.

Zeroconf, DHCP and manual steps only establish device facts and identity; the shared
confirm step collects the optional network SSID and is the only entry-creation point.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.service_info import dhcp, zeroconf
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import CONF_CFG, CONF_IP, CONF_MAC, CONF_SSID, CONF_TYPE, DOMAIN
from .errors import ModbusNotEnabledError
from .protocol.const import MAC_OUI, SUPPORT_DEVICE
from .runtime import SihasDeviceConfig
from .util import canonical_mac
from .composition import DeviceIdentityMismatch, get_composition
from .config_facts import InvalidSsid, UnsupportedDeviceType, config_data, default_name, device_config, normalize_ssid

_LOGGER = logging.getLogger(__name__)
_SSID_FIELD = vol.Optional(CONF_SSID)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Preserve discovery confirmation and canonical-MAC ConfigEntry identity."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._device: SihasDeviceConfig | None = None

    async def async_step_zeroconf(self, discovery_info: zeroconf.ZeroconfServiceInfo) -> ConfigFlowResult:
        try:
            parts = discovery_info.hostname.split(".")[0].split("_")
            device = device_config({
                CONF_IP: discovery_info.host, CONF_MAC: MAC_OUI + parts[2],
                CONF_TYPE: parts[1].upper(), CONF_CFG: int(discovery_info.properties[CONF_CFG], 16),
            })
        except UnsupportedDeviceType:
            return self.async_abort(reason="unsupported_device")
        except (IndexError, KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_input")
        await self.async_set_unique_id(device.mac)
        self._abort_if_unique_id_configured(updates={CONF_IP: device.ip})
        return await self._async_confirm_device(device)

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> ConfigFlowResult:
        # Keep the existing device-startup wait; scan itself runs in an executor.
        await asyncio.sleep(10)
        mac = canonical_mac(discovery_info.macaddress)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_IP: discovery_info.ip})
        try:
            device = await get_composition(self.hass).async_identify(discovery_info.ip, mac)
        except DeviceIdentityMismatch:
            return self.async_abort(reason="device_mismatch")
        except UnsupportedDeviceType:
            return self.async_abort(reason="unsupported_device")
        except (IndexError, KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_response")
        except OSError:
            return self.async_abort(reason="cannot_connect")
        if device is None:
            return self.async_abort(reason="cannot_connect")
        return await self._async_confirm_device(device)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input:
            try:
                device = device_config(user_input)
            except UnsupportedDeviceType:
                errors["base"] = "unsupported_device"
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                await self.async_set_unique_id(device.mac)
                self._abort_if_unique_id_configured()
                if (error := await self._async_validation_error(device)) is None:
                    return await self._async_confirm_device(device)
                errors["base"] = error
        schema = vol.Schema({
            vol.Required(CONF_IP): str, vol.Required(CONF_MAC): str,
            vol.Required(CONF_TYPE): vol.In(SUPPORT_DEVICE), vol.Required(CONF_CFG): int,
        })
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors)

    async def _async_confirm_device(self, device: SihasDeviceConfig) -> ConfigFlowResult:
        self._device = device
        self.context["title_placeholders"] = {CONF_TYPE: device.device_type, CONF_MAC: device.mac}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._device is not None
        errors = {}
        if user_input is not None:
            try:
                ssid = normalize_ssid(user_input.get(CONF_SSID))
            except InvalidSsid:
                errors[CONF_SSID] = "invalid_ssid"
            else:
                name = default_name(self._device)
                return self.async_create_entry(title=name, data=config_data(replace(self._device, name=name, ssid=ssid)))
        return self.async_show_form(
            step_id="confirm", data_schema=self.add_suggested_values_to_schema(vol.Schema({_SSID_FIELD: str}), user_input),
            description_placeholders={CONF_MAC: self._device.mac, CONF_TYPE: self._device.device_type}, errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                ssid = normalize_ssid(user_input.get(CONF_SSID))
                device = device_config({**entry.data, CONF_IP: user_input[CONF_IP]})
            except InvalidSsid:
                errors[CONF_SSID] = "invalid_ssid"
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                await self.async_set_unique_id(device.mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                if (error := await self._async_validation_error(device)) is None:
                    return self.async_update_reload_and_abort(entry, data_updates={CONF_IP: device.ip, CONF_SSID: ssid})
                errors["base"] = error
        schema = vol.Schema({vol.Required(CONF_IP): str, _SSID_FIELD: str})
        return self.async_show_form(
            step_id="reconfigure", data_schema=self.add_suggested_values_to_schema(schema, user_input or entry.data), errors=errors,
        )

    async def _async_validation_error(self, device: SihasDeviceConfig) -> str | None:
        """Communication check before an entry is created or changed; the form error key, or None on success."""
        try:
            await get_composition(self.hass).async_validate(device)
        except UpdateFailed as err:
            cause = err.__cause__
            if isinstance(cause, ModbusNotEnabledError):
                return "protocol_disabled"
            if isinstance(cause, OSError):
                return "cannot_connect"
            return "invalid_response"
        except Exception:
            _LOGGER.exception("Unexpected error validating SiHAS device %s", device.ip)
            return "unknown"
        return None
