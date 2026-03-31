"""Shared device info helper — kept in its own module to avoid circular imports."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, VERSION


def device_info_for_entry(entry: ConfigEntry) -> dict:
    """Return a DeviceInfo dict grouping all entities under one device per tent."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.title or "Small Grow Tent Controller",
        "manufacturer": "Small Grow Tent Controller",
        "model": "Grow Tent / Room",
        "sw_version": VERSION,
    }
