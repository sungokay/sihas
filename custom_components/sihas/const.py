"""Home Assistant-specific constants for the sihas integration.

Protocol/device-only facts (endianness, port, buffer size, accepted type
identifiers, the MAC OUI) live in `.protocol.const`, not here.
"""

from typing import Final

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
