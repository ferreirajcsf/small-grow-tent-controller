from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_info import device_info_for_entry
from .const import DOMAIN
from .notes import GrowJournalSensor

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
    # New in v0.1.24 — target conflict detection
    ("target_vpd_implied",  "Target VPD (Implied)",  None,  "kPa",  False),
    ("target_conflict_pct", "Target Conflict",       None,  "%",    False),
    ("target_implied_rh",   "Implied RH for Target VPD", None, "%", False),

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
    # Humidity/circulation device reasons
    ("debug_humidifier_reason",   "Humidifier Reason",   None,  None,  True),
    ("debug_dehumidifier_reason", "Dehumidifier Reason", None,  None,  True),
    ("debug_circulation_reason",  "Circulation Reason",  None,  None,  True),
    # Temperature target diagnostics
    ("debug_target_temp_c",       "Debug Target Temp",   SensorDeviceClass.TEMPERATURE, "°C",  True),
    ("debug_target_rh",           "Debug Target RH",     None,                          "%",   True),
    ("debug_ramped_target_temp_c","Ramped Target Temp",  SensorDeviceClass.TEMPERATURE, "°C",  True),
    # MPC runtime diagnostics
    ("debug_mpc_horizon",   "MPC Horizon",        None,  None,   True),
    ("debug_mpc_score",     "MPC Score",          None,  None,   True),
    ("debug_mpc_pred_temp", "MPC Predicted Temp", SensorDeviceClass.TEMPERATURE, "°C",  True),
    ("debug_mpc_pred_rh",   "MPC Predicted RH",   None,  "%",   True),
    ("debug_mpc_pred_vpd",  "MPC Predicted VPD",  None,  "kPa", True),
    ("debug_mpc_plan",      "MPC Action Plan",    None,  None,   True),
    # MPC model identification results
    ("mpc_r2_temp",  "MPC Model R² Temp",  None,  None,  True),
    ("mpc_r2_rh",    "MPC Model R² RH",    None,  None,  True),
    ("mpc_last_identified",  "MPC Last Identified",   None, None, True),
    ("debug_ambient_source", "MPC Ambient Source",    None, None, True),
    # Disturbance detection — disturbance_active is a BinarySensor (see binary_sensor.py)
    ("debug_disturbance_reason",       "Disturbance Reason",          None, None, True),
    ("debug_disturbance_remaining_s",  "Disturbance Hold Remaining",  None, "s",  True),

    # ── Observability ────────────────────────────────────────────────────────
    # VPD deadband performance — primary user-facing metric
    ("vpd_pct_in_band",       "VPD % In Target Band (24h)", None, "%",  False),
    ("vpd_pct_in_band_hours", "VPD Band Data Window",       None, "h",  False),
    ("vpd_out_of_band_s",     "VPD Out-of-Band Duration",   None, "s",  False),
    # Device toggle counters — TOTAL_INCREASING so HA natively computes rate/hour.
    # is_debug=False so they are enabled by default — HA only records statistics
    # for enabled entities, so disabling them by default would mean the statistics
    # graph has no data even after the user manually enables them later.
    ("heater_toggles",       "Heater Toggles",       None, None, False),
    ("exhaust_toggles",      "Exhaust Toggles",      None, None, False),
    ("humidifier_toggles",   "Humidifier Toggles",   None, None, False),
    ("dehumidifier_toggles", "Dehumidifier Toggles", None, None, False),
]

# Numeric sensors that should be recorded in long-term statistics
_MEASUREMENT_KEYS  = {"avg_temp_c", "avg_rh", "vpd_kpa", "dew_point_c",
                       "vpd_pct_in_band", "vpd_pct_in_band_hours", "vpd_out_of_band_s"}
_TOTAL_INCR_KEYS   = {"heater_toggles", "exhaust_toggles",
                       "humidifier_toggles", "dehumidifier_toggles"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        GrowTentSensor(entry, coordinator, key, name, devcls, unit, is_debug)
        for key, name, devcls, unit, is_debug in SENSORS
    ]
    # Add grow journal sensor (store already loaded by __init__.py)
    if hasattr(coordinator, '_notes_store'):
        journal = GrowJournalSensor(entry, coordinator._notes_store)
        coordinator._notes_sensor = journal
        entities.append(journal)
    async_add_entities(entities)


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
        elif key in _TOTAL_INCR_KEYS:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING

        # Debug sensors hidden from the default UI by default
        if is_debug:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.key)
