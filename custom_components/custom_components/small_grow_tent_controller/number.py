from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .device import device_info_for_entry

NUMBERS = [
    ("min_temp_c", "Min Temperature", 10.0, 35.0, 0.1, 20.0, "°C"),
    ("max_temp_c", "Max Temperature", 10.0, 35.0, 0.1, 30.0, "°C"),
    ("min_rh", "Min Humidity", 10.0, 95.0, 0.5, 40.0, "%"),
    ("max_rh", "Max Humidity", 10.0, 95.0, 0.5, 70.0, "%"),
    ("vpd_deadband_kpa", "VPD Deadband", 0.02, 0.30, 0.01, 0.07, "kPa"),
    ("dewpoint_margin_c", "Dew Point Margin", 0.2, 5.0, 0.1, 1.0, "°C"),
    ("heater_hold_s", "Heater Hold Time", 10.0, 600.0, 5.0, 60.0, "s"),
    ("heater_max_run_s", "Heater Max Run Time", 0.0, 600.0, 5.0, 0.0, "s"),
    ("exhaust_hold_s", "Exhaust Hold Time", 10.0, 600.0, 5.0, 45.0, "s"),
    ("humidifier_hold_s", "Humidifier Hold Time", 10.0, 600.0, 5.0, 45.0, "s"),
    ("dehumidifier_hold_s", "Dehumidifier Hold Time", 10.0, 600.0, 5.0, 45.0, "s"),
    ("leaf_temp_offset_c", "Leaf Temp Offset", -5.0, 5.0, 0.1, -1.5, "°C"),
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    async_add_entities([GrowNumber(hass, entry, *cfg) for cfg in NUMBERS])

class GrowNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                key: str, name: str, min_v: float, max_v: float, step: float, default: float, unit: str):
        self.hass = hass
        self.entry = entry
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = device_info_for_entry(entry)
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._value = default
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_numbers_{key}")

    async def async_added_to_hass(self):
        saved = await self.store.async_load()
        if isinstance(saved, dict) and "value" in saved:
            try:
                self._value = float(saved["value"])
            except Exception:
                pass
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self._value

    async def async_set_native_value(self, value: float):
        v = float(value)
        if self._attr_native_min_value is not None:
            v = max(v, self._attr_native_min_value)
        if self._attr_native_max_value is not None:
            v = min(v, self._attr_native_max_value)
        self._value = v
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()

