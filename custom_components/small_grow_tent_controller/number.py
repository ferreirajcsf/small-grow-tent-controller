from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from . import device_info_for_entry
from .const import (
    DOMAIN,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
    STAGE_TARGET_VPD_KPA,
    DEFAULT_STAGE,
)

# (key, name, min, max, step, default, unit)
NUMBERS = [
    ("min_temp_c",              "Min Temperature",              10.0, 35.0,  0.1,  20.0,  "°C"),
    ("max_temp_c",              "Max Temperature",              10.0, 35.0,  0.1,  30.0,  "°C"),
    ("min_rh",                  "Min Humidity",                 10.0, 95.0,  0.5,  40.0,  "%"),
    ("max_rh",                  "Max Humidity",                 10.0, 95.0,  0.5,  70.0,  "%"),
    ("vpd_target_kpa",          "VPD Target",                   0.40, 2.50,  0.01, 1.00,  "kPa"),
    ("vpd_deadband_kpa",        "VPD Deadband",                 0.02, 0.30,  0.01, 0.07,  "kPa"),
    ("dewpoint_margin_c",       "Dew Point Margin",             0.2,  5.0,   0.1,  1.0,   "°C"),
    ("heater_hold_s",           "Heater Hold Time",             10.0, 600.0, 5.0,  60.0,  "s"),
    ("heater_max_run_s",        "Heater Max Run Time",          0.0,  600.0, 5.0,  0.0,   "s"),
    ("exhaust_hold_s",          "Exhaust Hold Time",            10.0, 600.0, 5.0,  45.0,  "s"),
    ("exhaust_safety_max_temp_c","Exhaust Safety Max Temperature",10.0,45.0, 0.5,  30.0,  "°C"),
    ("exhaust_safety_max_rh",   "Exhaust Safety Max Humidity",  10.0, 99.0,  0.5,  75.0,  "%"),
    ("humidifier_hold_s",       "Humidifier Hold Time",         10.0, 600.0, 5.0,  45.0,  "s"),
    ("dehumidifier_hold_s",     "Dehumidifier Hold Time",       10.0, 600.0, 5.0,  45.0,  "s"),
    ("leaf_temp_offset_c",      "Leaf Temp Offset",             -5.0, 5.0,   0.1,  -1.5,  "°C"),
]


def _is_enabled(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    try:
        v = entry.options.get(key)
    except Exception:
        v = None
    return bool(v) if v is not None else default


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    use_heater       = _is_enabled(entry, CONF_USE_HEATER,       True)
    use_exhaust      = _is_enabled(entry, CONF_USE_EXHAUST,      True)
    use_humidifier   = _is_enabled(entry, CONF_USE_HUMIDIFIER,   True)
    use_dehumidifier = _is_enabled(entry, CONF_USE_DEHUMIDIFIER, True)

    selected = []
    for cfg in NUMBERS:
        key = cfg[0]
        if key in ("heater_hold_s", "heater_max_run_s") and not use_heater:
            continue
        if key in ("exhaust_hold_s", "exhaust_safety_max_temp_c", "exhaust_safety_max_rh") and not use_exhaust:
            continue
        if key == "humidifier_hold_s"   and not use_humidifier:
            continue
        if key == "dehumidifier_hold_s" and not use_dehumidifier:
            continue
        selected.append(cfg)

    entities = []
    for cfg in selected:
        if cfg[0] == "vpd_target_kpa":
            entities.append(VpdTargetNumber(hass, entry, *cfg))
        else:
            entities.append(GrowNumber(hass, entry, *cfg))

    async_add_entities(entities)


class GrowNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        self.hass  = hass
        self.entry = entry
        self.key   = key
        self._attr_unique_id                  = f"{entry.entry_id}_{key}"
        self._attr_name                       = name
        self._attr_native_min_value           = min_v
        self._attr_native_max_value           = max_v
        self._attr_native_step                = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info                = device_info_for_entry(entry)
        self._value  = default
        self.store   = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_numbers_{key}")

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
        v = max(self._attr_native_min_value, min(self._attr_native_max_value, float(value)))
        self._value = v
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()


class VpdTargetNumber(GrowNumber):
    """VPD Target number that auto-resets to the stage default when the stage changes.

    The coordinator calls async_set_to_stage_default() when it detects a stage change.
    The user can freely override the value at any time.
    """

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        super().__init__(hass, entry, key, name, min_v, max_v, step, default, unit)
        self._attr_icon = "mdi:gauge"

    async def async_set_to_stage_default(self, stage: str) -> None:
        """Called by the coordinator when stage changes — resets to the stage default."""
        default = STAGE_TARGET_VPD_KPA.get(stage, STAGE_TARGET_VPD_KPA[DEFAULT_STAGE])
        self._value = default
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()
