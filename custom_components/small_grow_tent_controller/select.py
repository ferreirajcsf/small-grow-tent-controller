from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, DEFAULT_STAGE, STAGE_TARGET_VPD_KPA

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    async_add_entities([StageSelect(hass, entry)])

class StageSelect(SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_stage"
        self._attr_name = "Stage"
        self._attr_options = list(STAGE_TARGET_VPD_KPA.keys())
        self._current = DEFAULT_STAGE
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_stage")

    async def async_added_to_hass(self):
        saved = await self.store.async_load()
        if isinstance(saved, dict) and saved.get("stage") in self._attr_options:
            self._current = saved["stage"]

    @property
    def current_option(self):
        return self._current

    async def async_select_option(self, option: str):
        if option not in self._attr_options:
            return
        self._current = option
        await self.store.async_save({"stage": self._current})
        self.async_write_ha_state()
