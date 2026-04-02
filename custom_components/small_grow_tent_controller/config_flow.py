from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DEFAULTS,
    DEFAULT_DEVICE_ENABLE,
    DOMAIN,
    CONF_USE_LIGHT,
    CONF_USE_CIRCULATION,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
    CONF_LIGHT_SWITCH,
    CONF_CIRC_SWITCH,
    CONF_EXHAUST_SWITCH,
    CONF_HEATER_SWITCH,
    CONF_HUMIDIFIER_SWITCH,
    CONF_DEHUMIDIFIER_SWITCH,
    CONF_TEMP_SENSOR_1,
    CONF_TEMP_SENSOR_2,
    CONF_TEMP_SENSOR_3,
    CONF_RH_SENSOR_1,
    CONF_RH_SENSOR_2,
    CONF_RH_SENSOR_3,
    CONF_AMBIENT_TEMP,
    CONF_AMBIENT_RH,
    CONF_WEATHER_ENTITY,
)


def _entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["switch", "sensor"])
    )


def _sensor_selector() -> selector.EntitySelector:
    """Sensor-only selector for ambient/environment entities."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["sensor"])
    )


def _weather_selector() -> selector.EntitySelector:
    """Weather entity selector."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["weather"])
    )


def _bool_selector() -> selector.BooleanSelector:
    return selector.BooleanSelector(selector.BooleanSelectorConfig())


class SmallGrowTentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Small Grow Tent Controller."""

    VERSION = 5

    def __init__(self) -> None:
        self._device_enable: dict[str, bool] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: choose which devices are present/enabled."""
        if user_input is not None:
            self._device_enable = {k: bool(user_input.get(k, True)) for k in DEFAULT_DEVICE_ENABLE}
            return await self.async_step_entities()

        schema = vol.Schema(
            {vol.Required(k, default=v): _bool_selector() for k, v in DEFAULT_DEVICE_ENABLE.items()}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_entities(self, user_input: dict[str, Any] | None = None):
        """Step 2: select entities (only for enabled devices)."""
        if user_input is not None:
            data = {**self._device_enable, **user_input}
            return self.async_create_entry(
                title="Small Grow Tent Controller",
                data=data,
            )

        schema_dict: dict[Any, Any] = {
            # Temperature sensors — 1 required, 2 and 3 optional
            vol.Required(CONF_TEMP_SENSOR_1): _sensor_selector(),
            vol.Optional(CONF_TEMP_SENSOR_2): _sensor_selector(),
            vol.Optional(CONF_TEMP_SENSOR_3): _sensor_selector(),
            # Humidity sensors — 1 required, 2 and 3 optional
            vol.Required(CONF_RH_SENSOR_1):   _sensor_selector(),
            vol.Optional(CONF_RH_SENSOR_2):   _sensor_selector(),
            vol.Optional(CONF_RH_SENSOR_3):   _sensor_selector(),
            # Optional lung room and weather
            vol.Optional(CONF_AMBIENT_TEMP):   _sensor_selector(),
            vol.Optional(CONF_AMBIENT_RH):     _sensor_selector(),
            vol.Optional(CONF_WEATHER_ENTITY): _weather_selector(),
        }

        if self._device_enable.get(CONF_USE_LIGHT, True):
            schema_dict[vol.Required(CONF_LIGHT_SWITCH, default=DEFAULTS[CONF_LIGHT_SWITCH])] = _entity_selector()
        if self._device_enable.get(CONF_USE_CIRCULATION, True):
            schema_dict[vol.Required(CONF_CIRC_SWITCH, default=DEFAULTS[CONF_CIRC_SWITCH])] = _entity_selector()
        if self._device_enable.get(CONF_USE_EXHAUST, True):
            schema_dict[vol.Required(CONF_EXHAUST_SWITCH, default=DEFAULTS[CONF_EXHAUST_SWITCH])] = _entity_selector()
        if self._device_enable.get(CONF_USE_HEATER, True):
            schema_dict[vol.Required(CONF_HEATER_SWITCH, default=DEFAULTS[CONF_HEATER_SWITCH])] = _entity_selector()
        if self._device_enable.get(CONF_USE_HUMIDIFIER, True):
            schema_dict[vol.Required(CONF_HUMIDIFIER_SWITCH, default=DEFAULTS[CONF_HUMIDIFIER_SWITCH])] = _entity_selector()
        if self._device_enable.get(CONF_USE_DEHUMIDIFIER, True):
            schema_dict[vol.Required(CONF_DEHUMIDIFIER_SWITCH, default=DEFAULTS[CONF_DEHUMIDIFIER_SWITCH])] = _entity_selector()

        return self.async_show_form(step_id="entities", data_schema=vol.Schema(schema_dict))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow handler — single step showing all settings at once."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Single options step: all settings on one screen."""
        defaults = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            # vol.Optional fields with suggested_value are NOT included in
            # user_input if the user does not explicitly interact with them.
            # Merge with defaults so no field is silently dropped.
            all_optional = [
                CONF_TEMP_SENSOR_2, CONF_TEMP_SENSOR_3,
                CONF_RH_SENSOR_2,   CONF_RH_SENSOR_3,
                CONF_AMBIENT_TEMP,  CONF_AMBIENT_RH, CONF_WEATHER_ENTITY,
                CONF_LIGHT_SWITCH,  CONF_CIRC_SWITCH, CONF_EXHAUST_SWITCH,
                CONF_HEATER_SWITCH, CONF_HUMIDIFIER_SWITCH, CONF_DEHUMIDIFIER_SWITCH,
            ]
            data = {**user_input}
            for key in all_optional:
                if key not in data:
                    data[key] = defaults.get(key, "")
            return self.async_create_entry(title="", data=data)

        schema_dict: dict[Any, Any] = {}

        # Device enable toggles
        for k, v in DEFAULT_DEVICE_ENABLE.items():
            schema_dict[vol.Required(k, default=bool(defaults.get(k, v)))] = _bool_selector()

        # Temperature sensors
        schema_dict[vol.Required(CONF_TEMP_SENSOR_1, default=defaults.get(CONF_TEMP_SENSOR_1, ""))] = _sensor_selector()
        schema_dict[vol.Optional(CONF_TEMP_SENSOR_2, description={"suggested_value": defaults.get(CONF_TEMP_SENSOR_2, "")})] = _sensor_selector()
        schema_dict[vol.Optional(CONF_TEMP_SENSOR_3, description={"suggested_value": defaults.get(CONF_TEMP_SENSOR_3, "")})] = _sensor_selector()

        # Humidity sensors
        schema_dict[vol.Required(CONF_RH_SENSOR_1, default=defaults.get(CONF_RH_SENSOR_1, ""))] = _sensor_selector()
        schema_dict[vol.Optional(CONF_RH_SENSOR_2, description={"suggested_value": defaults.get(CONF_RH_SENSOR_2, "")})] = _sensor_selector()
        schema_dict[vol.Optional(CONF_RH_SENSOR_3, description={"suggested_value": defaults.get(CONF_RH_SENSOR_3, "")})] = _sensor_selector()

        # Optional lung room sensors for MPC ambient tracking
        schema_dict[vol.Optional(CONF_AMBIENT_TEMP,   description={"suggested_value": defaults.get(CONF_AMBIENT_TEMP,   "")})] = _sensor_selector()
        schema_dict[vol.Optional(CONF_AMBIENT_RH,     description={"suggested_value": defaults.get(CONF_AMBIENT_RH,     "")})] = _sensor_selector()
        schema_dict[vol.Optional(CONF_WEATHER_ENTITY, description={"suggested_value": defaults.get(CONF_WEATHER_ENTITY, "")})] = _weather_selector()

        # Device switch assignments (always shown — user can clear if not using)
        schema_dict[vol.Optional(CONF_LIGHT_SWITCH,        description={"suggested_value": defaults.get(CONF_LIGHT_SWITCH,        "")})] = _entity_selector()
        schema_dict[vol.Optional(CONF_CIRC_SWITCH,         description={"suggested_value": defaults.get(CONF_CIRC_SWITCH,         "")})] = _entity_selector()
        schema_dict[vol.Optional(CONF_EXHAUST_SWITCH,      description={"suggested_value": defaults.get(CONF_EXHAUST_SWITCH,      "")})] = _entity_selector()
        schema_dict[vol.Optional(CONF_HEATER_SWITCH,       description={"suggested_value": defaults.get(CONF_HEATER_SWITCH,       "")})] = _entity_selector()
        schema_dict[vol.Optional(CONF_HUMIDIFIER_SWITCH,   description={"suggested_value": defaults.get(CONF_HUMIDIFIER_SWITCH,   "")})] = _entity_selector()
        schema_dict[vol.Optional(CONF_DEHUMIDIFIER_SWITCH, description={"suggested_value": defaults.get(CONF_DEHUMIDIFIER_SWITCH, "")})] = _entity_selector()

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
