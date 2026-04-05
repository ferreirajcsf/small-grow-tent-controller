from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .device_info import device_info_for_entry
from .const import DOMAIN, CONF_USE_EXHAUST, CONF_RLS_ENABLED, CONF_MPC_AUTO_IDENTIFY_WEEKLY


def _is_enabled(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    v = entry.options.get(key)
    if v is None:
        return default
    return bool(v)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    # One Store instance shared by all switches for this entry.
    # All switches read from and write to a single in-memory dict that is
    # loaded once here and then passed to each switch.  _save() writes the
    # entire dict atomically without a preceding load, eliminating the
    # load->mutate->save race that occurred when each switch owned its own
    # Store and two rapid toggles could overwrite each other.
    store      = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_state")
    saved_data = await store.async_load()
    state_dict = saved_data if isinstance(saved_data, dict) else {}

    entities: list[SwitchEntity] = [
        ControllerSwitch(hass, entry, store, state_dict),
        VpdChaseSwitch(hass, entry, store, state_dict),
        RlsSwitch(hass, entry, store, state_dict),
        MpcAutoIdentifySwitch(hass, entry, store, state_dict),
        DisturbanceSwitch(hass, entry, store, state_dict),
    ]
    if _is_enabled(entry, CONF_USE_EXHAUST, True):
        entities.append(ExhaustSafetyOverrideSwitch(hass, entry, store, state_dict))

    async_add_entities(entities)


class _StoredSwitch(SwitchEntity):
    """Base class for switches that persist their state to a shared HA storage file.

    All switch instances for a given config entry share one Store object and one
    in-memory dict (state_dict).  _save() writes the full dict in a single
    async_save call - no preceding load - so concurrent toggles cannot race and
    overwrite each other's state.
    """

    _attr_has_entity_name = True
    _store_key: str
    _default_on: bool = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: Store,
        state_dict: dict,
        unique_suffix: str,
    ):
        self.hass        = hass
        self.entry       = entry
        self._store      = store
        self._state_dict = state_dict   # shared mutable dict - all switches for this entry
        self._attr_unique_id   = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = device_info_for_entry(entry)
        self._is_on = bool(state_dict.get(self._store_key, self._default_on))

    async def async_added_to_hass(self) -> None:
        # State was already loaded into state_dict during async_setup_entry;
        # just apply it and write HA state.
        self._is_on = bool(self._state_dict.get(self._store_key, self._default_on))
        self.async_write_ha_state()

    async def _save(self) -> None:
        """Persist the current value atomically.

        Mutates the shared state_dict in place, then saves the whole dict in
        one call.  Because state_dict is shared and HA's event loop is
        single-threaded, there is no window where another switch can interleave
        between the mutation and the save.
        """
        self._state_dict[self._store_key] = self._is_on
        await self._store.async_save(self._state_dict)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        await self._save()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        await self._save()
        self.async_write_ha_state()


class ControllerSwitch(_StoredSwitch):
    _store_key  = "controller_is_on"
    _default_on = True

    def __init__(self, hass, entry, store, state_dict):
        super().__init__(hass, entry, store, state_dict, "controller")
        self._attr_name = "Controller"

    async def async_added_to_hass(self) -> None:
        # Backwards compat: old installations stored this key as "is_on"
        if "controller_is_on" in self._state_dict:
            self._is_on = bool(self._state_dict["controller_is_on"])
        elif "is_on" in self._state_dict:
            self._is_on = bool(self._state_dict["is_on"])
        else:
            self._is_on = self._default_on
        self.async_write_ha_state()


class VpdChaseSwitch(_StoredSwitch):
    """When ON (default), the controller chases VPD in day mode.
    When OFF, only hard limits are enforced - no VPD logic."""

    _store_key  = "vpd_chase_enabled"
    _default_on = True

    def __init__(self, hass, entry, store, state_dict):
        super().__init__(hass, entry, store, state_dict, "vpd_chase_enabled")
        self._attr_name = "VPD Chase"
        self._attr_icon = "mdi:chart-bubble"


class ExhaustSafetyOverrideSwitch(_StoredSwitch):
    """When enabled, prevents the exhaust from being forced OFF above safety thresholds."""

    _store_key  = "exhaust_safety_is_on"
    _default_on = False

    def __init__(self, hass, entry, store, state_dict):
        super().__init__(hass, entry, store, state_dict, "exhaust_safety_override")
        self._attr_name = "Exhaust Safety Override"


class RlsSwitch(_StoredSwitch):
    """When ON, the RLS algorithm continuously adapts the MPC model parameters
    from live observations. When OFF (default), model parameters stay fixed."""

    _store_key  = "rls_enabled"
    _default_on = False

    def __init__(self, hass, entry, store, state_dict):
        super().__init__(hass, entry, store, state_dict, CONF_RLS_ENABLED)
        self._attr_name = "RLS Adaptation"
        self._attr_icon = "mdi:chart-timeline-variant-shimmer"


class MpcAutoIdentifySwitch(_StoredSwitch):
    """When ON, automatically re-identifies the MPC model once per week."""

    _store_key  = "mpc_auto_identify_weekly"
    _default_on = False

    def __init__(self, hass, entry, store, state_dict):
        super().__init__(hass, entry, store, state_dict, CONF_MPC_AUTO_IDENTIFY_WEEKLY)
        self._attr_name = "MPC Auto-Identify Weekly"
        self._attr_icon = "mdi:calendar-refresh"


class DisturbanceSwitch(_StoredSwitch):
    """Manual disturbance trigger - turn ON before opening the tent to pre-emptively
    suppress control actions for the disturbance hold period.  The controller turns
    it back OFF automatically when the hold expires."""

    _store_key  = "disturbance_active"
    _default_on = False

    def __init__(self, hass, entry, store, state_dict):
        super().__init__(hass, entry, store, state_dict, "disturbance_active")
        self._attr_name = "Trigger Disturbance Hold"
        self._attr_icon = "mdi:alert-circle-outline"
