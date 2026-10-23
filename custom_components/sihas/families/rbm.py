"""RBM Home Assistant presentation owner."""
from __future__ import annotations

from homeassistant.components.cover import ATTR_POSITION, CoverEntity, CoverEntityFeature
from homeassistant.const import Platform
from typing_extensions import Final

from .registration import FamilyRegistration
from ..const import ICON_CURTAIN
from ..devices import rbm as rbm_semantics
from ..devices.definition import fixed
from ..devices.state import DeviceBinding
from ..entity import SihasEntity
from ..runtime import SihasRuntime


class Rbm300(SihasEntity, CoverEntity):
    """RBM-300 motorized cover.

    Home Assistant's `CoverDeviceClass` distinguishes exact physical subtypes (curtain,
    blind, shade, shutter, awning, garage, gate, door, damper, window) that this Task
    audited: the register protocol only exposes generic open/close/stop/percent-position
    control (motion and position commands), which is common to most of those
    subtypes and does not itself distinguish one. No repository documentation names the
    physical product beyond "RBM" plus its existing `mdi:curtains` icon, which by itself
    is not sufficient evidence for an exact device-class match (an icon choice predates
    and is independent of this audit). `device_class` is intentionally left unset rather
    than guessed; see `tests/test_entity_metadata.py` for the corresponding regression
    test documenting this evidence boundary.
    """

    _attr_icon = ICON_CURTAIN
    _attr_supported_features: Final = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, runtime: SihasRuntime) -> None:
        super().__init__(runtime, entity_key='cover')

    async def async_close_cover(self, **kwargs):
        await self.runtime.commands.async_execute("motion", "close")

    async def async_open_cover(self, **kwargs):
        await self.runtime.commands.async_execute("motion", "open")

    async def async_stop_cover(self, **kwargs):
        await self.runtime.commands.async_execute("motion", "stop")

    async def async_set_cover_position(self, **kwargs):
        await self.runtime.commands.async_execute("position", kwargs[ATTR_POSITION])

    def _project_state(self) -> None:
        state = self.coordinator.data.state
        self._attr_is_closed = state.closed
        self._attr_is_closing = state.closing
        self._attr_is_opening = state.opening
        self._attr_current_cover_position = state.position


FAMILY = FamilyRegistration(
    prepare=lambda config, firmware: DeviceBinding(fixed(rbm_semantics.DEFINITION)),
    entities={Platform.COVER: lambda runtime: [Rbm300(runtime)]},
)
