from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import device_info_for_entry
from .const import (
    DEFAULT_STAGE,
    DOMAIN,
    STAGE_TARGET_VPD_KPA,
    CONF_USE_LIGHT,
    CONF_USE_CIRCULATION,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
)

MODE_OPTIONS = ["Auto", "On", "Off"]


def _opt(entry: ConfigEntry, key: str, default):
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


@dataclass(frozen=True)
class _ModeDef:
    key: str
    name: str
    enable_conf: str


MODE_DEFS: list[_ModeDef] = [
    _ModeDef("light_mode", "Light Mode", CONF_USE_LIGHT),
    _ModeDef("circulation_mode", "Circulation Mode", CONF_USE_CIRCULATION),
    _ModeDef("exhaust_mode", "Exhaust Mode", CONF_USE_EXHAUST),
    _ModeDef("heater_mode", "Heater Mode", CONF_USE_HEATER),
    _ModeDef("humidifier_mode", "Humidifier Mode", CONF_USE_HUMIDIFIER),
    _ModeDef("dehumidifier_mode", "Dehumidifier Mode", CONF_USE_DEHUMIDIFIER),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    entities: list[SelectEntity] = [StageSelect(entry)]
    for d in MODE_DEFS:
        if bool(_opt(entry, d.enable_conf, True)):
            entities.append(DeviceModeSelect(entry, d.key, d.name))
    async_add_entities(entities)


class StageSelect(SelectEntity, RestoreEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_stage"
        self._attr_name = "Stage"
        self._attr_options = list(STAGE_TARGET_VPD_KPA.keys())
        self._attr_device_info = device_info_for_entry(entry)
        self._current = DEFAULT_STAGE

    async def async_added_to_hass(self):
        last = await self.async_get_last_state()
        if last and last.state in self._attr_options:
            self._current = last.state

    @property
    def current_option(self):
        return self._current

    async def async_select_option(self, option: str):
        if option not in self._attr_options:
            return
        self._current = option
        self.async_write_ha_state()


class DeviceModeSelect(SelectEntity, RestoreEntity):
    """Per-device manual override: Auto / On / Off."""

    _attr_has_entity_name = True
    _attr_options = MODE_OPTIONS

    def __init__(self, entry: ConfigEntry, key: str, name: str):
        self.entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = device_info_for_entry(entry)
        self._current = "Auto"

    async def async_added_to_hass(self):
        last = await self.async_get_last_state()
        if last and last.state in MODE_OPTIONS:
            self._current = last.state

    @property
    def current_option(self):
        return self._current

    async def async_select_option(self, option: str):
        if option not in MODE_OPTIONS:
            return
        self._current = option
        self.async_write_ha_state()
