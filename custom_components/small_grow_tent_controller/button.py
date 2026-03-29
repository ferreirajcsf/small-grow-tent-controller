from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_info import device_info_for_entry
from .const import DOMAIN
from .notes import ClearLastNoteButton, ClearAllNotesButton

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
    coordinator = hass.data[DOMAIN][entry.entry_id]
    buttons = [
        ReturnAllDevicesToAutoButton(hass, entry),
        MpcIdentifyButton(hass, entry, coordinator),
    ]
    # Add grow journal buttons — store is ready, sensor ref filled in later by sensor platform
    if hasattr(coordinator, '_notes_store'):
        buttons.append(ClearLastNoteButton(entry, coordinator))
        buttons.append(ClearAllNotesButton(entry, coordinator))
    async_add_entities(buttons)


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

class MpcIdentifyButton(ButtonEntity):
    """Triggers MPC model re-identification from HA history.

    Runs OLS regression on the last N days of sensor history (configurable
    via the MPC Identification Days number entity), writes the fitted
    parameters to the MPC number entities, records results in the Grow
    Journal, and updates the R² diagnostic sensors.
    """
    _attr_has_entity_name = True
    _attr_icon = "mdi:calculator-variant"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        self.hass        = hass
        self.entry       = entry
        self._coordinator = coordinator
        self._attr_unique_id   = f"{entry.entry_id}_mpc_identify"
        self._attr_name        = "Re-identify MPC Model"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        _LOGGER.info("MPC Re-identify button pressed")
        result = await self._coordinator.async_identify_model()
        if "error" in result:
            _LOGGER.error("MPC identification failed: %s", result["error"])
        else:
            _LOGGER.info(
                "MPC identification complete — R²(temp)=%.3f R²(RH)=%.3f",
                result.get("r2_temp", 0), result.get("r2_rh", 0),
            )
