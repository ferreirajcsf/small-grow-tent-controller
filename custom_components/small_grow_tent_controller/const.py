DOMAIN = "small_grow_tent_controller"
VERSION = "0.1.59"

PLATFORMS = ["sensor", "switch", "select", "number", "time", "binary_sensor", "button"]

# Fixed entity-id option keys
CONF_LIGHT_SWITCH        = "light_switch"
CONF_CIRC_SWITCH         = "circulation_switch"
CONF_EXHAUST_SWITCH      = "exhaust_switch"
CONF_HEATER_SWITCH       = "heater_switch"
CONF_HUMIDIFIER_SWITCH   = "humidifier_switch"
CONF_DEHUMIDIFIER_SWITCH = "dehumidifier_switch"

# Enable/disable device control (lets user omit devices they don't have)
CONF_USE_LIGHT        = "use_light"
CONF_USE_CIRCULATION  = "use_circulation"
CONF_USE_EXHAUST      = "use_exhaust"
CONF_USE_HEATER       = "use_heater"
CONF_USE_HUMIDIFIER   = "use_humidifier"
CONF_USE_DEHUMIDIFIER = "use_dehumidifier"

CONF_CANOPY_TEMP   = "canopy_temp"
CONF_TOP_TEMP      = "top_temp"
CONF_CANOPY_RH     = "canopy_rh"
CONF_TOP_RH        = "top_rh"
CONF_AMBIENT_TEMP  = "ambient_temp"   # optional lung room temp sensor
CONF_AMBIENT_RH    = "ambient_rh"     # optional lung room RH sensor

# Defaults — empty so the config flow doesn't pre-fill with someone else's entity IDs
DEFAULTS = {
    CONF_LIGHT_SWITCH:        "",
    CONF_CIRC_SWITCH:         "",
    CONF_EXHAUST_SWITCH:      "",
    CONF_HEATER_SWITCH:       "",
    CONF_HUMIDIFIER_SWITCH:   "",
    CONF_DEHUMIDIFIER_SWITCH: "",
    CONF_CANOPY_TEMP:         "",
    CONF_TOP_TEMP:            "",
    CONF_CANOPY_RH:           "",
    CONF_TOP_RH:              "",
    CONF_AMBIENT_TEMP:        "",   # optional
    CONF_AMBIENT_RH:          "",   # optional
}

# Which devices are enabled by default in the UI
DEFAULT_DEVICE_ENABLE = {
    CONF_USE_LIGHT:        True,
    CONF_USE_CIRCULATION:  True,
    CONF_USE_EXHAUST:      True,
    CONF_USE_HEATER:       True,
    CONF_USE_HUMIDIFIER:   True,
    CONF_USE_DEHUMIDIFIER: True,
}

# Default VPD targets (kPa) per growth stage — used as the slider reset value
# when the user changes stage. Can be overridden freely via the VPD Target number entity.
STAGE_TARGET_VPD_KPA = {
    "Seedling":          0.70,
    "Early Vegetative":  0.95,
    "Late Vegetative":   1.10,
    "Early Bloom":       1.25,
    "Late Bloom":        1.45,
    "Drying":            0.90,
}

# Target temperature (°C) per stage — used as the slider reset value on stage change.
# Represents the ideal canopy temperature the controller should chase during the day.
STAGE_TARGET_TEMP_C = {
    "Seedling":          24.0,
    "Early Vegetative":  25.0,
    "Late Vegetative":   26.0,
    "Early Bloom":       26.0,
    "Late Bloom":        25.0,
    "Drying":            21.0,
}

# Target humidity (% RH) per stage — used as the slider reset value on stage change.
# Represents the ideal RH the controller should chase during the day.
STAGE_TARGET_RH = {
    "Seedling":          70.0,
    "Early Vegetative":  60.0,
    "Late Vegetative":   55.0,
    "Early Bloom":       50.0,
    "Late Bloom":        45.0,
    "Drying":            55.0,
}

DEFAULT_STAGE = "Early Vegetative"

# Exhaust safety override (optional)
CONF_EXHAUST_SAFETY_OVERRIDE  = "exhaust_safety_override"
CONF_EXHAUST_SAFETY_MAX_TEMP_C = "exhaust_safety_max_temp_c"
CONF_EXHAUST_SAFETY_MAX_RH    = "exhaust_safety_max_rh"

# VPD Chase switch unique-id suffix
CONF_VPD_CHASE_ENABLED = "vpd_chase_enabled"

# Night mode select options
CONF_NIGHT_MODE          = "night_mode"
NIGHT_MODE_DEW           = "Dew Protection"        # classic pulse-to-dew behaviour
NIGHT_MODE_VPD           = "VPD Chase"              # full VPD chase + dew floor
NIGHT_MODE_VPD_NO_HEATER = "VPD Chase (No Heater)" # VPD chase + dew floor, heater excluded from chasing
NIGHT_MODE_MPC           = "MPC"                    # MPC using night targets + dew floor
NIGHT_MODE_OPTIONS       = [NIGHT_MODE_DEW, NIGHT_MODE_VPD, NIGHT_MODE_VPD_NO_HEATER, NIGHT_MODE_MPC]

# Night VPD Chase switch unique-id suffix
CONF_NIGHT_VPD_CHASE = "night_vpd_chase"

# Day control mode select options
CONF_DAY_MODE       = "day_mode"
DAY_MODE_VPD        = "VPD Chase"
DAY_MODE_MPC        = "MPC"
DAY_MODE_LIMITS     = "Limits Only"
DAY_MODE_OPTIONS    = [DAY_MODE_VPD, DAY_MODE_MPC, DAY_MODE_LIMITS]

# Night target defaults per stage (temp = day - 5°C, RH auto-computed for same VPD)
STAGE_NIGHT_TARGET_TEMP_C = {
    "Seedling":          19.0,
    "Early Vegetative":  20.0,
    "Late Vegetative":   21.0,
    "Early Bloom":       21.0,
    "Late Bloom":        20.0,
    "Drying":            16.0,
}

STAGE_NIGHT_TARGET_VPD_KPA = {
    "Seedling":          0.70,
    "Early Vegetative":  0.95,
    "Late Vegetative":   1.10,
    "Early Bloom":       1.25,
    "Late Bloom":        1.45,
    "Drying":            0.90,
}

STAGE_NIGHT_TARGET_RH = {
    "Seedling":          59.2,
    "Early Vegetative":  50.5,
    "Late Vegetative":   46.9,
    "Early Bloom":       40.9,
    "Late Bloom":        29.1,
    "Drying":            41.3,
}

# Exhaust mode extended options (day/night schedule awareness)
EXHAUST_MODE_DAY_ON   = "Day On"   # on during day window, off at night
EXHAUST_MODE_NIGHT_ON = "Night On" # on during night window, off during day
EXHAUST_MODE_OPTIONS  = ["Auto", "On", "Off", EXHAUST_MODE_DAY_ON, EXHAUST_MODE_NIGHT_ON]

# Temperature ramp rate config key
CONF_TEMP_RAMP_RATE = "temp_ramp_rate_c_per_min"

# RLS (Recursive Least Squares) online model adaptation
CONF_RLS_ENABLED              = "rls_enabled"
CONF_MPC_AUTO_IDENTIFY_WEEKLY = "mpc_auto_identify_weekly"
