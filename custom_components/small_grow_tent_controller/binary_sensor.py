from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import device_info_for_entry
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
    key:     str
    name:    str
    icon:    str
    default: bool = True


USE_FLAGS: tuple[_UseFlagDescription, ...] = (
    _UseFlagDescription(CONF_USE_LIGHT,         "Use Light Control",           "mdi:lightbulb-on-10"),
    _UseFlagDescription(CONF_USE_CIRCULATION,   "Use Circulation Fan Control", "mdi:fan"),
    _UseFlagDescription(CONF_USE_EXHAUST,       "Use Exhaust Fan Control",     "mdi:fan-chevron-up"),
    _UseFlagDescription(CONF_USE_HEATER,        "Use Heater Control",          "mdi:radiator"),
    _UseFlagDescription(CONF_USE_HUMIDIFIER,    "Use Humidifier Control",      "mdi:air-humidifier"),
    _UseFlagDescription(CONF_USE_DEHUMIDIFIER,  "Use Dehumidifier Control",    "mdi:water-off"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [
        GrowTentUseFlagBinarySensor(entry, desc) for desc in USE_FLAGS
    ]
    # New in v0.1.15 — sensor availability problem indicator
    entities.append(SensorsUnavailableBinarySensor(entry, coordinator))

    async_add_entities(entities)


class GrowTentUseFlagBinarySensor(BinarySensorEntity):
    """Read-only mirror of whether a given device is enabled in the integration config."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, desc: _UseFlagDescription) -> None:
        self._entry = entry
        self._desc  = desc
        self._attr_name        = desc.name
        self._attr_icon        = desc.icon
        self._attr_unique_id   = f"{entry.entry_id}_{desc.key}"
        self._attr_device_info = device_info_for_entry(entry)

    @property
    def is_on(self) -> bool:
        opts = self._entry.options or {}
        data = self._entry.data    or {}
        if self._desc.key in opts:
            return bool(opts[self._desc.key])
        if self._desc.key in data:
            return bool(data[self._desc.key])
        return bool(self._desc.default)


class SensorsUnavailableBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """
    Binary sensor that turns ON when one or more environment sensors
    are unavailable or returning invalid readings.

    ON  = problem (sensors missing)
    OFF = all sensors healthy
    """

    _attr_has_entity_name  = True
    _attr_device_class     = BinarySensorDeviceClass.PROBLEM
    _attr_icon             = "mdi:alert-circle-outline"

    def __init__(self, entry: ConfigEntry, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id   = f"{entry.entry_id}_sensors_unavailable"
        self._attr_name        = "Sensors Unavailable"
        self._attr_device_info = device_info_for_entry(entry)

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("sensors_unavailable", False))
