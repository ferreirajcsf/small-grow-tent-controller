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
    CONF_CANOPY_TEMP,
    CONF_TOP_TEMP,
    CONF_CANOPY_RH,
    CONF_TOP_RH,
    CONF_AMBIENT_TEMP,
    CONF_AMBIENT_RH,
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


def _bool_selector() -> selector.BooleanSelector:
    return selector.BooleanSelector(selector.BooleanSelectorConfig())


async def async_migrate_entry(hass, config_entry: config_entries.ConfigEntry) -> bool:
    """Migrate existing config entries to the current version.

    v3 → v4: added optional ambient_temp and ambient_rh sensor fields.
    These default to empty string (disabled) so all existing entries
    continue to work without any user action required.
    """
    if config_entry.version < 4:
        new_data = {**config_entry.data}
        new_data.setdefault("ambient_temp", "")
        new_data.setdefault("ambient_rh",   "")
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=4,
        )
    return True


class SmallGrowTentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Small Grow Tent Controller."""

    VERSION = 4

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
            vol.Required(CONF_CANOPY_TEMP, default=DEFAULTS[CONF_CANOPY_TEMP]): _entity_selector(),
            vol.Required(CONF_TOP_TEMP, default=DEFAULTS[CONF_TOP_TEMP]): _entity_selector(),
            vol.Required(CONF_CANOPY_RH, default=DEFAULTS[CONF_CANOPY_RH]): _entity_selector(),
            vol.Required(CONF_TOP_RH, default=DEFAULTS[CONF_TOP_RH]): _entity_selector(),
            vol.Optional(CONF_AMBIENT_TEMP): _sensor_selector(),
            vol.Optional(CONF_AMBIENT_RH):   _sensor_selector(),
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
    """Options flow handler for Small Grow Tent Controller."""

    def __init__(self) -> None:
        self._device_enable: dict[str, bool] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Options step 1: device enable flags."""
        if user_input is not None:
            self._device_enable = {k: bool(user_input.get(k, True)) for k in DEFAULT_DEVICE_ENABLE}
            return await self.async_step_entities()

        defaults = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {vol.Required(k, default=bool(defaults.get(k, v))): _bool_selector() for k, v in DEFAULT_DEVICE_ENABLE.items()}
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_entities(self, user_input: dict[str, Any] | None = None):
        """Options step 2: entity selection for enabled devices."""
        if user_input is not None:
            # Preserve ambient sensor fields even if left blank —
            # vol.Optional fields may be absent from user_input when empty
            existing = {**self.config_entry.data, **self.config_entry.options}
            data = {
                **self._device_enable,
                **user_input,
                CONF_AMBIENT_TEMP: user_input.get(CONF_AMBIENT_TEMP, existing.get(CONF_AMBIENT_TEMP, "")),
                CONF_AMBIENT_RH:   user_input.get(CONF_AMBIENT_RH,   existing.get(CONF_AMBIENT_RH,   "")),
            }
            return self.async_create_entry(title="", data=data)

        defaults = {**self.config_entry.data, **self.config_entry.options, **self._device_enable}

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_CANOPY_TEMP, default=defaults.get(CONF_CANOPY_TEMP, DEFAULTS[CONF_CANOPY_TEMP])): _entity_selector(),
            vol.Required(CONF_TOP_TEMP, default=defaults.get(CONF_TOP_TEMP, DEFAULTS[CONF_TOP_TEMP])): _entity_selector(),
            vol.Required(CONF_CANOPY_RH, default=defaults.get(CONF_CANOPY_RH, DEFAULTS[CONF_CANOPY_RH])): _entity_selector(),
            vol.Required(CONF_TOP_RH, default=defaults.get(CONF_TOP_RH, DEFAULTS[CONF_TOP_RH])): _entity_selector(),
            vol.Optional(CONF_AMBIENT_TEMP, description={"suggested_value": defaults.get(CONF_AMBIENT_TEMP, "")}): _sensor_selector(),
            vol.Optional(CONF_AMBIENT_RH,   description={"suggested_value": defaults.get(CONF_AMBIENT_RH,   "")}): _sensor_selector(),
        }

        if defaults.get(CONF_USE_LIGHT, True):
            schema_dict[vol.Required(CONF_LIGHT_SWITCH, default=defaults.get(CONF_LIGHT_SWITCH, DEFAULTS[CONF_LIGHT_SWITCH]))] = _entity_selector()
        if defaults.get(CONF_USE_CIRCULATION, True):
            schema_dict[vol.Required(CONF_CIRC_SWITCH, default=defaults.get(CONF_CIRC_SWITCH, DEFAULTS[CONF_CIRC_SWITCH]))] = _entity_selector()
        if defaults.get(CONF_USE_EXHAUST, True):
            schema_dict[vol.Required(CONF_EXHAUST_SWITCH, default=defaults.get(CONF_EXHAUST_SWITCH, DEFAULTS[CONF_EXHAUST_SWITCH]))] = _entity_selector()
        if defaults.get(CONF_USE_HEATER, True):
            schema_dict[vol.Required(CONF_HEATER_SWITCH, default=defaults.get(CONF_HEATER_SWITCH, DEFAULTS[CONF_HEATER_SWITCH]))] = _entity_selector()
        if defaults.get(CONF_USE_HUMIDIFIER, True):
            schema_dict[vol.Required(CONF_HUMIDIFIER_SWITCH, default=defaults.get(CONF_HUMIDIFIER_SWITCH, DEFAULTS[CONF_HUMIDIFIER_SWITCH]))] = _entity_selector()
        if defaults.get(CONF_USE_DEHUMIDIFIER, True):
            schema_dict[vol.Required(CONF_DEHUMIDIFIER_SWITCH, default=defaults.get(CONF_DEHUMIDIFIER_SWITCH, DEFAULTS[CONF_DEHUMIDIFIER_SWITCH]))] = _entity_selector()

        return self.async_show_form(step_id="entities", data_schema=vol.Schema(schema_dict))
