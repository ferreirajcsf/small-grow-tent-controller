from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

SENSORS = [
    ("avg_temp_c", "Average Temperature", SensorDeviceClass.TEMPERATURE, "°C"),
    ("avg_rh", "Average Humidity", SensorDeviceClass.HUMIDITY, "%"),
    ("vpd_kpa", "VPD", None, "kPa"),
    ("dew_point_c", "Dew Point", SensorDeviceClass.TEMPERATURE, "°C"),
    ("control_mode", "Control Mode", None, None),
    ("leaf_temp_c", "Leaf Temperature", SensorDeviceClass.TEMPERATURE, "°C"),
    ("leaf_temp_offset_c", "Leaf Temp Offset", SensorDeviceClass.TEMPERATURE, "°C"),

    # Debug / diagnostics (time + schedule)
    ("debug_local_time", "Controller Local Time", None, None),
    ("debug_local_tod", "Controller Local Time (TOD)", None, None),
    ("debug_is_day", "Controller Is Day", None, None),
    ("debug_light_window", "Light Window", None, None),
    ("debug_light_reason", "Light Decision Reason", None, None),

    # Debug / diagnostics (exhaust policy)
    ("debug_exhaust_policy", "Exhaust Policy", None, None),
    ("debug_exhaust_reason", "Exhaust Reason", None, None),

    # Debug / diagnostics (heater ramp/pulse)
    ("debug_heater_target_c", "Heater Target", SensorDeviceClass.TEMPERATURE, "°C"),
    ("debug_heater_error_c", "Heater Error", SensorDeviceClass.TEMPERATURE, "°C"),
    ("debug_heater_reason", "Heater Reason", None, None),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [GrowTentSensor(entry, coordinator, key, name, devcls, unit) for key, name, devcls, unit in SENSORS]
    )


class GrowTentSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, coordinator, key, name, devcls, unit):
        super().__init__(coordinator)
        self.entry = entry
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_class = devcls
        self._attr_native_unit_of_measurement = unit

        if key in ("avg_temp_c", "avg_rh", "vpd_kpa", "dew_point_c"):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.key)
