from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .device import device_info_for_entry

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    async_add_entities([ControllerSwitch(hass, entry)])

class ControllerSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_controller"
        self._attr_name = "Controller"
        self._attr_device_info = device_info_for_entry(entry)
        self._is_on = True
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_state")

    async def async_added_to_hass(self):
        saved = await self.store.async_load()
        if isinstance(saved, dict) and "is_on" in saved:
            self._is_on = bool(saved["is_on"])

    @property
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        await self.store.async_save({"is_on": self._is_on})
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        await self.store.async_save({"is_on": self._is_on})
        self.async_write_ha_state()
