from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_USE_LIGHT,
    CONF_USE_CIRCULATION,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
)


@dataclass(frozen=True)
class _UseFlagDescription:
    key: str
    name: str
    icon: str
    default: bool = True


USE_FLAGS: tuple[_UseFlagDescription, ...] = (
    _UseFlagDescription(CONF_USE_LIGHT, "Use Light Control", "mdi:lightbulb-on-10"),
    _UseFlagDescription(CONF_USE_CIRCULATION, "Use Circulation Fan Control", "mdi:fan"),
    _UseFlagDescription(CONF_USE_EXHAUST, "Use Exhaust Fan Control", "mdi:fan-chevron-up"),
    _UseFlagDescription(CONF_USE_HEATER, "Use Heater Control", "mdi:radiator"),
    _UseFlagDescription(CONF_USE_HUMIDIFIER, "Use Humidifier Control", "mdi:air-humidifier"),
    _UseFlagDescription(CONF_USE_DEHUMIDIFIER, "Use Dehumidifier Control", "mdi:water-off"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([GrowTentUseFlagBinarySensor(entry, desc) for desc in USE_FLAGS])


class GrowTentUseFlagBinarySensor(BinarySensorEntity):
    """Binary sensor that mirrors whether a given device is enabled in the integration."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, desc: _UseFlagDescription) -> None:
        self._entry = entry
        self._desc = desc

        self._attr_name = desc.name
        self._attr_icon = desc.icon
        self._attr_unique_id = f"{entry.entry_id}_{desc.key}"

        # Group these under a single device in the UI.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Small Grow Tent Controller",
        }

    @property
    def is_on(self) -> bool:
        # Default to True for backwards-compatibility (older entries didn't have use_* flags).
        return bool(self._entry.data.get(self._desc.key, self._desc.default))
