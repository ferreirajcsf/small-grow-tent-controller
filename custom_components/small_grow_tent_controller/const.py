DOMAIN = "small_grow_tent_controller"
VERSION = "0.1.14"

PLATFORMS = ["sensor", "switch", "select", "number", "time", "binary_sensor", "button"]

# Fixed entity-id option keys
CONF_LIGHT_SWITCH = "light_switch"
CONF_CIRC_SWITCH = "circulation_switch"
CONF_EXHAUST_SWITCH = "exhaust_switch"
CONF_HEATER_SWITCH = "heater_switch"
CONF_HUMIDIFIER_SWITCH = "humidifier_switch"
CONF_DEHUMIDIFIER_SWITCH = "dehumidifier_switch"

# Enable/disable device control (lets user omit devices they don't have)
CONF_USE_LIGHT = "use_light"
CONF_USE_CIRCULATION = "use_circulation"
CONF_USE_EXHAUST = "use_exhaust"
CONF_USE_HEATER = "use_heater"
CONF_USE_HUMIDIFIER = "use_humidifier"
CONF_USE_DEHUMIDIFIER = "use_dehumidifier"

CONF_CANOPY_TEMP = "canopy_temp"
CONF_TOP_TEMP = "top_temp"
CONF_CANOPY_RH = "canopy_rh"
CONF_TOP_RH = "top_rh"

# Defaults — empty so the config flow doesn't pre-fill with someone else's entity IDs
DEFAULTS = {
    CONF_LIGHT_SWITCH: "",
    CONF_CIRC_SWITCH: "",
    CONF_EXHAUST_SWITCH: "",
    CONF_HEATER_SWITCH: "",
    CONF_HUMIDIFIER_SWITCH: "",
    CONF_DEHUMIDIFIER_SWITCH: "",
    CONF_CANOPY_TEMP: "",
    CONF_TOP_TEMP: "",
    CONF_CANOPY_RH: "",
    CONF_TOP_RH: "",
}

# Which devices are enabled by default in the UI
DEFAULT_DEVICE_ENABLE = {
    CONF_USE_LIGHT: True,
    CONF_USE_CIRCULATION: True,
    CONF_USE_EXHAUST: True,
    CONF_USE_HEATER: True,
    CONF_USE_HUMIDIFIER: True,
    CONF_USE_DEHUMIDIFIER: True,
}

# Stage targets (kPa) - representative cannabis guidance
STAGE_TARGET_VPD_KPA = {
    "Seedling": 0.70,
    "Vegetative": 1.00,
    "Early Flower": 1.10,
    "Mid Flower": 1.30,
    "Late Flower": 1.50,
    "Drying": 0.90,
}

DEFAULT_STAGE = "Vegetative"

# Exhaust safety override (optional)
CONF_EXHAUST_SAFETY_OVERRIDE = "exhaust_safety_override"
CONF_EXHAUST_SAFETY_MAX_TEMP_C = "exhaust_safety_max_temp_c"
CONF_EXHAUST_SAFETY_MAX_RH = "exhaust_safety_max_rh"
