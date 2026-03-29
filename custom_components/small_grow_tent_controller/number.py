from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .device_info import device_info_for_entry
from .const import (
    DOMAIN,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
    STAGE_TARGET_VPD_KPA,
    STAGE_TARGET_TEMP_C,
    STAGE_TARGET_RH,
    STAGE_NIGHT_TARGET_TEMP_C,
    STAGE_NIGHT_TARGET_VPD_KPA,
    STAGE_NIGHT_TARGET_RH,
    DEFAULT_STAGE,
)

# (key, name, min, max, step, default, unit)
NUMBERS = [
    ("min_temp_c",              "Min Temperature",              10.0, 35.0,  0.1,  20.0,  "°C"),
    ("max_temp_c",              "Max Temperature",              10.0, 35.0,  0.1,  30.0,  "°C"),
    ("min_rh",                  "Min Humidity",                 10.0, 95.0,  0.5,  40.0,  "%"),
    ("max_rh",                  "Max Humidity",                 10.0, 95.0,  0.5,  70.0,  "%"),
    ("vpd_target_kpa",          "VPD Target",                   0.40, 2.50,  0.01, 1.00,  "kPa"),
    ("target_temp_c",           "Target Temperature",           10.0, 35.0,  0.1,  25.0,  "°C"),
    ("target_rh",               "Target Humidity",              10.0, 95.0,  0.5,  55.0,  "%"),
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
    ("night_vpd_target_kpa",    "Night VPD Target",             0.40, 2.50,  0.01, 1.00,  "kPa"),
    ("night_target_temp_c",     "Night Target Temperature",     10.0, 35.0,  0.1,  20.0,  "°C"),
    ("night_target_rh",         "Night Target Humidity",        10.0, 95.0,  0.5,  55.0,  "%"),
    ("temp_ramp_rate_c_per_min","Temp Ramp Rate",               0.0,  5.0,   0.1,  1.0,   "°C/min"),
    # MPC model parameters
    ("mpc_horizon_steps",       "MPC Horizon Steps",            1,    6,     1,    3,     "steps"),
    ("mpc_temp_amb",            "MPC Ambient Temp",             5.0,  35.0,  0.1,  20.0,  "°C"),
    ("mpc_rh_amb",              "MPC Ambient RH",               10.0, 95.0,  0.5,  55.0,  "%"),
    ("mpc_a_heater",            "MPC a_heater",                 -2.0, 2.0,   0.001, 0.423, "°C/step"),
    ("mpc_a_exhaust",           "MPC a_exhaust",                -2.0, 2.0,   0.001,-0.082, "°C/step"),
    ("mpc_a_passive",           "MPC a_passive",                0.0,  0.5,   0.001, 0.008, "/step"),
    ("mpc_a_bias",              "MPC a_bias",                   -1.0, 1.0,   0.001, 0.057, "°C/step"),
    ("mpc_b_exhaust",           "MPC b_exhaust",                -5.0, 5.0,   0.01, -1.196, "%/step"),
    ("mpc_b_passive",           "MPC b_passive",                0.0,  0.5,   0.001, 0.006, "/step"),
    ("mpc_b_bias",              "MPC b_bias",                   -5.0, 5.0,   0.01,  0.556, "%/step"),
    ("mpc_w_vpd",               "MPC Weight VPD",               0.0,  10.0,  0.1,  5.0,   ""),
    ("mpc_w_temp",              "MPC Weight Temp",              0.0,  10.0,  0.1,  2.0,   ""),
    ("mpc_w_rh",                "MPC Weight RH",                0.0,  10.0,  0.1,  1.0,   ""),
    ("mpc_w_switch",            "MPC Switch Penalty",           0.0,  5.0,   0.1,  0.5,   ""),
    # RLS parameters
    ("rls_forgetting_factor",   "RLS Forgetting Factor",        0.990, 1.000, 0.001, 0.999, ""),
    # MPC model identification
    ("mpc_identify_days",       "MPC Identification Days",      1,    30,    1,     7,     "days"),
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
        elif cfg[0] == "target_temp_c":
            entities.append(TempTargetNumber(hass, entry, *cfg))
        elif cfg[0] == "target_rh":
            entities.append(RhTargetNumber(hass, entry, *cfg))
        elif cfg[0] == "night_vpd_target_kpa":
            entities.append(NightVpdTargetNumber(hass, entry, *cfg))
        elif cfg[0] == "night_target_temp_c":
            entities.append(NightTempTargetNumber(hass, entry, *cfg))
        elif cfg[0] == "night_target_rh":
            entities.append(NightRhTargetNumber(hass, entry, *cfg))
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


class TempTargetNumber(GrowNumber):
    """Target Temperature number that auto-resets to the stage default when the stage changes."""

    _attr_suggested_display_precision = 1

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        super().__init__(hass, entry, key, name, min_v, max_v, step, default, unit)
        self._attr_icon = "mdi:thermometer"

    async def async_set_to_stage_default(self, stage: str) -> None:
        """Called by the coordinator when stage changes — resets to the stage default."""
        default = STAGE_TARGET_TEMP_C.get(stage, STAGE_TARGET_TEMP_C[DEFAULT_STAGE])
        self._value = default
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()


class RhTargetNumber(GrowNumber):
    """Target Humidity number that auto-resets to the stage default when the stage changes."""

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        super().__init__(hass, entry, key, name, min_v, max_v, step, default, unit)
        self._attr_icon = "mdi:water-percent"

    async def async_set_to_stage_default(self, stage: str) -> None:
        """Called by the coordinator when stage changes — resets to the stage default."""
        default = STAGE_TARGET_RH.get(stage, STAGE_TARGET_RH[DEFAULT_STAGE])
        self._value = default
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()

class NightVpdTargetNumber(GrowNumber):
    """Night VPD Target — auto-resets to stage default on stage change."""

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        super().__init__(hass, entry, key, name, min_v, max_v, step, default, unit)
        self._attr_icon = "mdi:weather-night"

    async def async_set_to_stage_default(self, stage: str) -> None:
        default = STAGE_NIGHT_TARGET_VPD_KPA.get(stage, STAGE_NIGHT_TARGET_VPD_KPA[DEFAULT_STAGE])
        self._value = default
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()


class NightTempTargetNumber(GrowNumber):
    """Night Target Temperature — auto-resets to stage default (day - 5°C) on stage change."""

    _attr_suggested_display_precision = 1

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        super().__init__(hass, entry, key, name, min_v, max_v, step, default, unit)
        self._attr_icon = "mdi:thermometer-minus"

    async def async_set_to_stage_default(self, stage: str) -> None:
        default = STAGE_NIGHT_TARGET_TEMP_C.get(stage, STAGE_NIGHT_TARGET_TEMP_C[DEFAULT_STAGE])
        self._value = default
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()


class NightRhTargetNumber(GrowNumber):
    """Night Target Humidity — auto-resets to stage default (RH for night temp + VPD) on stage change."""

    _attr_suggested_display_precision = 0

    def __init__(self, hass, entry, key, name, min_v, max_v, step, default, unit):
        super().__init__(hass, entry, key, name, min_v, max_v, step, default, unit)
        self._attr_icon = "mdi:water-percent"

    async def async_set_to_stage_default(self, stage: str) -> None:
        default = STAGE_NIGHT_TARGET_RH.get(stage, STAGE_NIGHT_TARGET_RH[DEFAULT_STAGE])
        self._value = default
        await self.store.async_save({"value": self._value})
        self.async_write_ha_state()
