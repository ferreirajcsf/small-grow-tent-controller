from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, CONF_NAME, DEFAULT_NAME


def device_info_for_entry(entry: ConfigEntry) -> dict:
    """Return a DeviceInfo dict that groups all entities per tent/room."""
    name = (
        entry.options.get(CONF_NAME)
        or entry.data.get(CONF_NAME)
        or entry.title
        or DEFAULT_NAME
    )

    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": str(name),
        "manufacturer": "Small Grow Tent Controller",
        "model": "Grow Tent / Room",
        "sw_version": "0.1.3",
    }
