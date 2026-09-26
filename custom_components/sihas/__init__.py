"""The sihas integration."""
from __future__ import annotations

from functools import partial
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .runtime import SihasConfigEntry
from .validation import device_config, get_validation

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = [
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
]


async def async_setup_entry(hass: HomeAssistant, entry: SihasConfigEntry) -> bool:
    try:
        device_config(entry.data)
        validation = get_validation(hass)
        observation = await validation.async_refresh_firmware(entry)
        device = device_config(entry.data)
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryError(f"Invalid SiHAS configuration: {err}") from err
    # Operational facts come from the entry; the observation is display-only.
    runtime = validation.create_runtime(device, entry, observation)
    if runtime.commands is not None:
        entry.async_on_unload(runtime.commands.async_shutdown)
    if coordinator := runtime.coordinator:
        # HA raises ConfigEntryNotReady on communication/protocol failure and
        # shuts down the coordinator on failed/cancelled setup.
        await coordinator.async_config_entry_first_refresh()
    # Fix this setup's device-information projection to the first publication so
    # every platform registers the same metadata; polling continues unchanged.
    _ = runtime.device_metadata
    entry.runtime_data = runtime
    # Platforms receive the complete first publication. Successful unload or
    # cancelled forwarding releases runtime; failed unload retains its ownership.
    entry.async_on_unload(partial(delattr, entry, "runtime_data"))
    _LOGGER.debug("Set up SiHAS config entry %s", entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SihasConfigEntry) -> bool:
    _LOGGER.debug("Unloading SiHAS config entry %s", entry.entry_id)
    commands = entry.runtime_data.commands
    unload_ok = False
    try:
        # Close admission before platform removal or waiting for active commands.
        # HA cannot replace this runtime until this integration unload returns.
        if commands is not None:
            await commands.async_quiesce()
        if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            if commands is not None:
                await commands.async_shutdown()
            unload_ok = True
        return unload_ok
    finally:
        # False, exception or cancellation retains the old runtime in HA.
        if not unload_ok and commands is not None:
            commands.resume()
