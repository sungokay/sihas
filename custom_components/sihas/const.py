"""Home Assistant-specific constants for the sihas integration.

Protocol/device-only facts (endianness, port, buffer size, accepted type
identifiers, the MAC OUI) live in `.protocol.const`, not here.
"""

from typing import Final

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.climate import PLATFORM_SCHEMA

DOMAIN: Final = "sihas"
ATTRIBUTION: Final = "SiHAS IoT Device"

# configuration variables
CONF_NAME: Final = "name"
CONF_IP: Final = "ip"
CONF_MAC: Final = "mac"
CONF_TYPE: Final = "type"
CONF_SSID: Final = "ssid"
CONF_CFG: Final = "cfg"
CONF_FIRMWARE: Final = "firmware"

# icons
ICON_BUTTON: Final = "mdi:radiobox-marked"
ICON_COOLER: Final = "mdi:air-conditioner"
ICON_CURTAIN: Final = "mdi:curtains"
ICON_HEATER: Final = "mdi:thermostat"
ICON_LIGHT_BULB: Final = "mdi:lightbulb-variant"
ICON_POWER_METER: Final = "mdi:transmission-tower"
ICON_POWER_SOCKET: Final = "mdi:power-socket-de"


DEFAULT_PARALLEL_UPDATES: Final = 5


SIHAS_PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_IP): cv.string,
        vol.Required(CONF_MAC): cv.string,
        vol.Required(CONF_TYPE): cv.string,
        vol.Required(CONF_CFG): cv.positive_int,
    }
)
