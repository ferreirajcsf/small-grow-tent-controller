from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from . import device_info_for_entry
from .const import DOMAIN, CONF_USE_EXHAUST


def _is_enabled(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    try:
        v = entry.options.get(key)
    except Exception:
        v = None
    if v is None:
        return default
    return bool(v)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    entities: list[SwitchEntity] = [
        ControllerSwitch(hass, entry),
        VpdChaseSwitch(hass, entry),
    ]
    if _is_enabled(entry, CONF_USE_EXHAUST, True):
        entities.append(ExhaustSafetyOverrideSwitch(hass, entry))

    async_add_entities(entities)


class _StoredSwitch(SwitchEntity):
    """Base class for switches that persist their state to HA storage."""

    _attr_has_entity_name = True
    _store_key: str       # key used inside the shared JSON file
    _default_on: bool = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, unique_suffix: str):
        self.hass  = hass
        self.entry = entry
        self._attr_unique_id   = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = device_info_for_entry(entry)
        self._is_on = self._default_on
        self.store  = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_state")

    async def async_added_to_hass(self):
        saved = await self.store.async_load()
        if isinstance(saved, dict) and self._store_key in saved:
            self._is_on = bool(saved[self._store_key])
        self.async_write_ha_state()

    async def _save(self) -> None:
        saved = await self.store.async_load()
        data  = saved if isinstance(saved, dict) else {}
        data[self._store_key] = self._is_on
        await self.store.async_save(data)

    @property
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        await self._save()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        await self._save()
        self.async_write_ha_state()


class ControllerSwitch(_StoredSwitch):
    _store_key  = "controller_is_on"
    _default_on = True

    def __init__(self, hass, entry):
        super().__init__(hass, entry, "controller")
        self._attr_name = "Controller"

    async def async_added_to_hass(self):
        # Backwards compat: old key was "is_on"
        saved = await self.store.async_load()
        if isinstance(saved, dict):
            if self._store_key in saved:
                self._is_on = bool(saved[self._store_key])
            elif "is_on" in saved:
                self._is_on = bool(saved["is_on"])
        self.async_write_ha_state()


class VpdChaseSwitch(_StoredSwitch):
    """When ON (default), the controller chases VPD in day mode.
    When OFF, only hard limits are enforced — no VPD logic."""

    _store_key  = "vpd_chase_enabled"
    _default_on = True

    def __init__(self, hass, entry):
        super().__init__(hass, entry, "vpd_chase_enabled")
        self._attr_name = "VPD Chase"
        self._attr_icon = "mdi:chart-bubble"


class ExhaustSafetyOverrideSwitch(_StoredSwitch):
    """When enabled, prevents the exhaust from being forced OFF above safety thresholds."""

    _store_key  = "exhaust_safety_is_on"
    _default_on = False

    def __init__(self, hass, entry):
        super().__init__(hass, entry, "exhaust_safety_override")
        self._attr_name = "Exhaust Safety Override"
