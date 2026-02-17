from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version == 1:
        data = dict(entry.data)

        def _infer(use_key: str, entity_key: str) -> None:
            if use_key not in data:
                data[use_key] = bool(data.get(entity_key))

        _infer(CONF_USE_LIGHT, CONF_LIGHT_SWITCH)
        _infer(CONF_USE_CIRCULATION, CONF_CIRC_SWITCH)
        _infer(CONF_USE_EXHAUST, CONF_EXHAUST_SWITCH)
        _infer(CONF_USE_HEATER, CONF_HEATER_SWITCH)
        _infer(CONF_USE_HUMIDIFIER, CONF_HUMIDIFIER_SWITCH)
        _infer(CONF_USE_DEHUMIDIFIER, CONF_DEHUMIDIFIER_SWITCH)

        hass.config_entries.async_update_entry(entry, data=data, version=2)
        return True

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GrowTentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
