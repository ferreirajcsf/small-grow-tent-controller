DOMAIN = "small_grow_tent_controller"

PLATFORMS = ["sensor", "switch", "select", "number", "time"]

# Fixed entity-id option keys
CONF_LIGHT_SWITCH = "light_switch"
CONF_CIRC_SWITCH = "circulation_switch"
CONF_EXHAUST_SWITCH = "exhaust_switch"
CONF_HEATER_SWITCH = "heater_switch"
CONF_HUMIDIFIER_SWITCH = "humidifier_switch"
CONF_DEHUMIDIFIER_SWITCH = "dehumidifier_switch"

CONF_CANOPY_TEMP = "canopy_temp"
CONF_TOP_TEMP = "top_temp"
CONF_CANOPY_RH = "canopy_rh"
CONF_TOP_RH = "top_rh"

# Defaults (your entities)
DEFAULTS = {
    CONF_LIGHT_SWITCH: "switch.lightgrowtent",
    CONF_CIRC_SWITCH: "switch.ventilationgrowtent",  # you called this circulation/ventilation
    CONF_EXHAUST_SWITCH: "switch.exhaustgrowtent",
    CONF_HEATER_SWITCH: "switch.heatergrowtent",
    # NEW (optional): humidity devices
    CONF_HUMIDIFIER_SWITCH: "switch.humidifiergrowtent",
    CONF_DEHUMIDIFIER_SWITCH: "switch.dehumidifiergrowtent",
    CONF_CANOPY_TEMP: "sensor.canopy_temperature",
    CONF_TOP_TEMP: "sensor.top_temperature",
    CONF_CANOPY_RH: "sensor.canopy_humidity",
    CONF_TOP_RH: "sensor.top_humidity",
}

# Stage targets (kPa) - representative cannabis guidance
# Targets are representative VPD midpoints; adjust as desired.
STAGE_TARGET_VPD_KPA = {
    "Seedling": 0.70,
    "Vegetative": 1.00,
    "Early Flower": 1.10,
    "Mid Flower": 1.30,
    "Late Flower": 1.50,
    "Drying": 0.90,
}

DEFAULT_STAGE = "Vegetative"
