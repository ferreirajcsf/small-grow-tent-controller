from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULTS, DOMAIN, CONF_NAME, DEFAULT_NAME


def _entity_selector() -> selector.EntitySelector:
    """Return an entity selector for the entities this integration consumes."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["switch", "sensor"])
    )


class SmallGrowTentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Small Grow Tent Controller."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            title = user_input.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(
                title=str(title),
                data=user_input,
            )

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )
        }
        schema_dict.update({vol.Required(k, default=v): _entity_selector() for k, v in DEFAULTS.items() if k != CONF_NAME})
        schema = vol.Schema(schema_dict)

        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow handler for Small Grow Tent Controller."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {**self.config_entry.data, **self.config_entry.options}

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )
        }
        schema_dict.update(
            {
                vol.Required(k, default=defaults.get(k, v)): _entity_selector()
                for k, v in DEFAULTS.items()
                if k != CONF_NAME
            }
        )
        schema = vol.Schema(schema_dict)

        return self.async_show_form(step_id="init", data_schema=schema)
