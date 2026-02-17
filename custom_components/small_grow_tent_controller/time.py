from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_USE_LIGHT

TIMES = [
    ("light_on", "Light On Time", time(8, 0, 0)),
    ("light_off", "Light Off Time", time(20, 0, 0)),
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    use_light = entry.options.get(CONF_USE_LIGHT)
    if use_light is None:
        use_light = True

    # If the user disables light control, hide the schedule entities.
    if not bool(use_light):
        async_add_entities([])
        return

    async_add_entities([GrowTime(hass, entry, *cfg) for cfg in TIMES])

class GrowTime(TimeEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str, name: str, default: time):
        self.hass = hass
        self.entry = entry
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._value = default
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_time_{key}")

    async def async_added_to_hass(self):
        saved = await self.store.async_load()
        if isinstance(saved, dict) and "value" in saved:
            try:
                hh, mm, ss = (saved["value"].split(":") + ["0", "0"])[:3]
                self._value = time(int(hh), int(mm), int(ss))
            except Exception:
                pass

    @property
    def native_value(self):
        return self._value

    async def async_set_value(self, value: time):
        self._value = value
        await self.store.async_save({"value": value.strftime("%H:%M:%S")})
        self.async_write_ha_state()
