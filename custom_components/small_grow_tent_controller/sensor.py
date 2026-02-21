from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import device_info_for_entry
from .const import DOMAIN

# (key, name, device_class, unit, is_debug)
SENSORS = [
    # Primary operational sensors
    ("avg_temp_c",    "Average Temperature", SensorDeviceClass.TEMPERATURE, "°C",  False),
    ("avg_rh",        "Average Humidity",    SensorDeviceClass.HUMIDITY,    "%",   False),
    ("vpd_kpa",       "VPD",                 None,                          "kPa", False),
    ("dew_point_c",   "Dew Point",           SensorDeviceClass.TEMPERATURE, "°C",  False),
    ("control_mode",  "Control Mode",        None,                          None,  False),
    ("leaf_temp_c",   "Leaf Temperature",    SensorDeviceClass.TEMPERATURE, "°C",  False),
    ("leaf_temp_offset_c", "Leaf Temp Offset", SensorDeviceClass.TEMPERATURE, "°C", False),
    # New in v0.1.15
    ("last_action",   "Last Action",         None,                          None,  False),

    # Debug / diagnostics — hidden by default (enable via Settings → Entities)
    ("debug_local_time",    "Controller Local Time",      None,                          None,  True),
    ("debug_local_tod",     "Controller Local Time (TOD)",None,                          None,  True),
    ("debug_is_day",        "Controller Is Day",          None,                          None,  True),
    ("debug_light_window",  "Light Window",               None,                          None,  True),
    ("debug_light_reason",  "Light Decision Reason",      None,                          None,  True),
    ("debug_exhaust_policy","Exhaust Policy",             None,                          None,  True),
    ("debug_exhaust_reason","Exhaust Reason",             None,                          None,  True),
    ("debug_heater_target_c","Heater Target",             SensorDeviceClass.TEMPERATURE, "°C",  True),
    ("debug_heater_error_c", "Heater Error",              SensorDeviceClass.TEMPERATURE, "°C",  True),
    ("debug_heater_reason",  "Heater Reason",             None,                          None,  True),
    ("debug_heater_on_for_s","Heater On For",             None,                          "s",   True),
    ("debug_heater_max_run_s","Heater Max Run",           None,                          "s",   True),
    ("debug_heater_lockout", "Heater Lockout",            None,                          None,  True),
]

# Numeric sensors that should be recorded in long-term statistics
_MEASUREMENT_KEYS = {"avg_temp_c", "avg_rh", "vpd_kpa", "dew_point_c"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        GrowTentSensor(entry, coordinator, key, name, devcls, unit, is_debug)
        for key, name, devcls, unit, is_debug in SENSORS
    ])


class GrowTentSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, coordinator, key, name, devcls, unit, is_debug):
        super().__init__(coordinator)
        self.entry = entry
        self.key   = key
        self._attr_unique_id                  = f"{entry.entry_id}_{key}"
        self._attr_name                       = name
        self._attr_device_class               = devcls
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info                = device_info_for_entry(entry)

        if key in _MEASUREMENT_KEYS:
            self._attr_state_class = SensorStateClass.MEASUREMENT

        # Debug sensors hidden from the default UI by default
        if is_debug:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.key)
