"""Workflow UX over shared configured facts and async-safe device validation."""
from __future__ import annotations

import asyncio
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.service_info import dhcp, zeroconf
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import CONF_CFG, CONF_IP, CONF_MAC, CONF_NAME, CONF_TYPE, DOMAIN
from .errors import ModbusNotEnabledError
from .protocol.const import MAC_OUI, SUPPORT_DEVICE
from .util import canonical_mac
from .validation import DeviceIdentityMismatch, UnsupportedDeviceType, config_data, device_config, get_validation


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Preserve discovery confirmation and canonical-MAC ConfigEntry identity."""

    VERSION = 1

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def async_step_zeroconf(self, discovery_info: zeroconf.ZeroconfServiceInfo) -> ConfigFlowResult:
        try:
            parts = discovery_info.hostname.split(".")[0].split("_")
            device = device_config({
                CONF_IP: discovery_info.host, CONF_MAC: MAC_OUI + parts[2],
                CONF_TYPE: parts[1].upper(), CONF_CFG: int(discovery_info.properties[CONF_CFG], 16),
            })
        except UnsupportedDeviceType as err:
            return self.async_abort(reason=f"not supported device type: {err}")
        except (IndexError, KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_input")
        self.data = config_data(device)
        await self.async_set_unique_id(device.mac)
        self._abort_if_unique_id_configured(updates={CONF_IP: device.ip})
        return await self._async_discovery_confirm()

    async def _async_discovery_confirm(self) -> ConfigFlowResult:
        self.context["title_placeholders"] = {CONF_TYPE: self.data[CONF_TYPE], CONF_MAC: self.data[CONF_MAC]}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input:
            self.data[CONF_NAME] = user_input[CONF_NAME]
            return self.async_create_entry(title=self.data[CONF_TYPE], data=self.data)
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=self.data[CONF_TYPE] + self.data[CONF_MAC]): cv.string}),
            description_placeholders={CONF_MAC: self.data[CONF_MAC], CONF_TYPE: self.data[CONF_TYPE]},
        )

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> ConfigFlowResult:
        # Keep the existing device-startup wait; scan itself runs in an executor.
        await asyncio.sleep(10)
        mac = canonical_mac(discovery_info.macaddress)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_IP: discovery_info.ip})
        try:
            device = await get_validation(self.hass).async_identify(discovery_info.ip, mac)
        except DeviceIdentityMismatch:
            return self.async_abort(reason="device scanned but ip does not match")
        except UnsupportedDeviceType as err:
            return self.async_abort(reason=f"not supported device type: {err}")
        except (IndexError, KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_response")
        except OSError:
            return self.async_abort(reason="can not scan found device")
        if device is None:
            return self.async_abort(reason="can not scan found device")
        self.data = config_data(device)
        return await self._async_discovery_confirm()

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
                try:
                    await get_validation(self.hass).async_validate(device)
                except UpdateFailed as err:
                    cause = err.__cause__
                    if isinstance(cause, ModbusNotEnabledError):
                        errors["base"] = "protocol_disabled"
                    elif isinstance(cause, OSError):
                        errors["base"] = "cannot_connect"
                    else:
                        errors["base"] = "invalid_response"
                else:
                    self.data = config_data(device)
                    return self.async_create_entry(title=device.name, data=self.data)
        schema = vol.Schema({
            vol.Required(CONF_IP): str, vol.Required(CONF_MAC): str,
            vol.Required(CONF_TYPE): vol.In(SUPPORT_DEVICE), vol.Required(CONF_CFG): int, vol.Required(CONF_NAME): str,
        })
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors)
