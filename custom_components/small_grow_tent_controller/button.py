from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import device_info_for_entry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MODE_KEYS = [
    "light_mode",
    "circulation_mode",
    "exhaust_mode",
    "heater_mode",
    "humidifier_mode",
    "dehumidifier_mode",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    async_add_entities([ReturnAllDevicesToAutoButton(hass, entry)])


class ReturnAllDevicesToAutoButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_return_all_to_auto"
        self._attr_name = "Return All Devices to Auto"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        registry = er.async_get(self.hass)

        entity_ids: list[str] = []
        for key in MODE_KEYS:
            unique_id = f"{self.entry.entry_id}_{key}"
            eid = registry.async_get_entity_id("select", DOMAIN, unique_id)
            if eid:
                entity_ids.append(eid)

        if not entity_ids:
            _LOGGER.debug("No mode select entities found to reset to Auto.")
            return

        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_ids, "option": "Auto"},
            blocking=True,
        )
