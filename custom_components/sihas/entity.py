"""HA identity and publication projection shared by the maintained platforms."""
from __future__ import annotations

from typing import Optional

from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_IP, CONF_MAC, CONF_TYPE, DOMAIN
from .coordinator import SihasCoordinator
from .runtime import SihasRuntime


def sihas_device_info(mac: str, device_type: str, name: Optional[str] = None) -> DeviceInfo:
    """Build the single canonical Device Registry contract for a physical SiHAS unit.

    `mac` must already be the canonical MAC address (see `util.canonical_mac`). Every
    entity belonging to the same physical device is given the same `mac`/`device_type`/`name`
    here so they resolve to one Device Registry device with one consistent display name.
    `name` is the user-facing device name (e.g. the config-entry title); it falls back to
    `device_type` when not supplied, but carries no identity meaning either way.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, mac)},
        connections={(CONNECTION_NETWORK_MAC, mac)},
        manufacturer="SiHAS",
        model=device_type,
        name=name or device_type,
    )


def sihas_unique_id(mac: str, entity_key: str) -> str:
    """Build a SiHAS entity's Home Assistant unique ID.

    `entity_unique_id = canonical_device_identifier + "-" + entity_key`. `mac`
    must already be the canonical MAC address; `entity_key` is the entity's immutable semantic
    role (never metadata such as device_class, unit, display name, device type, or IP).
    """
    return f"{mac}-{entity_key}"


class SihasEntityGroup:
    """Presentation factory input; owns neither state nor communication."""

    def __init__(self, runtime: SihasRuntime) -> None:
        self.runtime = runtime


class SihasProjection(CoordinatorEntity[SihasCoordinator]):
    """Project a complete coordinator publication into HA presentation attributes."""

    _attr_has_entity_name = True
    # HA attribute names whose values this projection itself generates. Diagnostics
    # exports them as generated evidence only while the sampled value still equals
    # this loaded producer's own current output.
    diagnostic_generated_attributes: frozenset[str] = frozenset()

    def __init__(self, runtime: SihasRuntime, *, entity_key: str, translation_key: str | None = None,
                 translation_placeholders: dict[str, str] | None = None) -> None:
        assert runtime.coordinator is not None
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self.entity_key = entity_key
        self._attr_unique_id = sihas_unique_id(runtime.device.mac, entity_key)
        if translation_key:
            self._attr_translation_key = translation_key
            if translation_placeholders:
                self._attr_translation_placeholders = translation_placeholders

    @property
    def device_info(self):
        device = self.runtime.device
        return sihas_device_info(device.mac, device.device_type, device.name)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._project_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data is not None:
            self._project_state()
        super()._handle_coordinator_update()

    def _project_state(self) -> None:
        """Copy only HA presentation values; buttons have no device state to copy."""


class SihasEntity(SihasProjection):
    """Whole-device entity attributes retained from the pre-coordinator platforms."""

    def __init__(self, runtime: SihasRuntime, **kwargs) -> None:
        super().__init__(runtime, **kwargs)
        self._attributes = {}
        self._state = None

    @property
    def extra_state_attributes(self) -> dict:
        device = self.runtime.device
        return {ATTR_ATTRIBUTION: ATTRIBUTION, **self._attributes,
                CONF_MAC: device.mac, CONF_IP: device.ip, CONF_TYPE: device.device_type}
