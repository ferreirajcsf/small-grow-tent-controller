from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    VERSION,
    PLATFORMS,
    CONF_USE_LIGHT,
    CONF_USE_CIRCULATION,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
    CONF_LIGHT_SWITCH,
    CONF_CIRC_SWITCH,
    CONF_EXHAUST_SWITCH,
    CONF_HEATER_SWITCH,
    CONF_HUMIDIFIER_SWITCH,
    CONF_DEHUMIDIFIER_SWITCH,
)
from .coordinator import GrowTentCoordinator


# Re-exported for backwards compatibility
from .device_info import device_info_for_entry  # noqa: F401


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current schema version."""

    if entry.version == 1:
        # v1 → v2: add device enable flags inferred from entity presence
        data = dict(entry.data)

        def _infer(use_key: str, entity_key: str) -> None:
            if use_key not in data:
                data[use_key] = bool(data.get(entity_key))

        _infer(CONF_USE_LIGHT,        CONF_LIGHT_SWITCH)
        _infer(CONF_USE_CIRCULATION,  CONF_CIRC_SWITCH)
        _infer(CONF_USE_EXHAUST,      CONF_EXHAUST_SWITCH)
        _infer(CONF_USE_HEATER,       CONF_HEATER_SWITCH)
        _infer(CONF_USE_HUMIDIFIER,   CONF_HUMIDIFIER_SWITCH)
        _infer(CONF_USE_DEHUMIDIFIER, CONF_DEHUMIDIFIER_SWITCH)

        hass.config_entries.async_update_entry(entry, data=data, version=2)
        # Fall through to v2 → v3

    if entry.version == 2:
        # v2 → v3: no data changes needed; new switch/number entities
        # (vpd_chase_enabled, vpd_target_kpa) are created with safe defaults
        # by their respective entity classes on first load.
        hass.config_entries.async_update_entry(entry, version=3)
        return True

    if entry.version == 3:
        # v3 → v4: added optional ambient_temp and ambient_rh sensor fields
        data = dict(entry.data)
        data.setdefault("ambient_temp", "")
        data.setdefault("ambient_rh",   "")
        hass.config_entries.async_update_entry(entry, data=data, version=4)
        return True

    if entry.version == 4:
        return True

    # Unknown future version — refuse to load
    return False


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GrowTentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    from .notes import async_setup_notes_store
    await async_setup_notes_store(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
