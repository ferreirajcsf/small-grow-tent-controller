from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_USE_EXHAUST


def _is_enabled(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    try:
        v = entry.options.get(key)
    except Exception:
        v = None
    if v is None:
        return default
    return bool(v)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    entities: list[SwitchEntity] = [ControllerSwitch(hass, entry)]

    # Optional exhaust safety override switch (only when exhaust control is enabled)
    if _is_enabled(entry, CONF_USE_EXHAUST, True):
        entities.append(ExhaustSafetyOverrideSwitch(hass, entry))

    async_add_entities(entities)


class _SharedStateStoreMixin:
    """Shared storage for switch states, so we can persist multiple switches without multiple files."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_state")

    async def _load(self) -> dict:
        saved = await self.store.async_load()
        return saved if isinstance(saved, dict) else {}

    async def _save(self, patch: dict) -> None:
        saved = await self._load()
        saved.update(patch)
        await self.store.async_save(saved)


class ControllerSwitch(_SharedStateStoreMixin, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_controller"
        self._attr_name = "Controller"
        self._is_on = True

    async def async_added_to_hass(self):
        saved = await self._load()

        # Backwards compatible with older versions that stored {"is_on": ...}
        if "controller_is_on" in saved:
            self._is_on = bool(saved["controller_is_on"])
        elif "is_on" in saved:
            self._is_on = bool(saved["is_on"])

        self.async_write_ha_state()

    @property
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        await self._save({"controller_is_on": self._is_on})
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        await self._save({"controller_is_on": self._is_on})
        self.async_write_ha_state()


class ExhaustSafetyOverrideSwitch(_SharedStateStoreMixin, SwitchEntity):
    """When enabled, prevents the exhaust fan from being forced OFF if temp/RH exceed thresholds."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_exhaust_safety_override"
        self._attr_name = "Exhaust Safety Override"
        self._is_on = False  # opt-in

    async def async_added_to_hass(self):
        saved = await self._load()
        if "exhaust_safety_is_on" in saved:
            self._is_on = bool(saved["exhaust_safety_is_on"])
        self.async_write_ha_state()

    @property
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        await self._save({"exhaust_safety_is_on": self._is_on})
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        await self._save({"exhaust_safety_is_on": self._is_on})
        self.async_write_ha_state()
