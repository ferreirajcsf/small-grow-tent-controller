"""
Grow Journal — persistent dated notes.

Storage:  .storage/small_grow_tent_controller.notes.<entry_id>
Schema:   {"notes": [{"ts": "2026-02-24 14:30", "text": "..."}]}

Entities are registered through the normal sensor/button platform setup
in sensor.py and button.py respectively.  This file provides:
  - NotesStore      — persistence
  - GrowJournalSensor, ClearLastNoteButton, ClearAllNotesButton — entities
  - async_setup_notes_store() — creates + loads the store, attaches to coordinator
  - register_add_note_service() — registers the HA service (called once)
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .device_info import device_info_for_entry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_MAX_NOTES = 100


# ── Storage ───────────────────────────────────────────────────────────────────

class NotesStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}.notes.{entry_id}")
        self._notes: list[dict[str, str]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data and isinstance(data.get("notes"), list):
            self._notes = data["notes"]

    @property
    def notes(self) -> list[dict[str, str]]:
        return list(self._notes)

    async def async_add(self, text: str) -> None:
        ts = dt_util.as_local(dt_util.utcnow()).strftime("%Y-%m-%d %H:%M")
        self._notes.append({"ts": ts, "text": text.strip()})
        if len(self._notes) > _MAX_NOTES:
            self._notes = self._notes[-_MAX_NOTES:]
        await self._store.async_save({"notes": self._notes})

    async def async_clear_last(self) -> None:
        if self._notes:
            self._notes.pop()
            await self._store.async_save({"notes": self._notes})

    async def async_clear_all(self) -> None:
        self._notes = []
        await self._store.async_save({"notes": self._notes})


# ── Sensor ────────────────────────────────────────────────────────────────────

class GrowJournalSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Grow Journal"
    _attr_icon = "mdi:notebook-edit-outline"
    _attr_native_unit_of_measurement = "notes"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, store: NotesStore) -> None:
        self._store = store
        self._attr_unique_id   = f"{entry.entry_id}_grow_journal"
        self._attr_device_info = device_info_for_entry(entry)

    @property
    def native_value(self) -> int:
        return len(self._store.notes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        notes = self._store.notes
        return {
            "notes": list(reversed(notes)),
            "latest": notes[-1] if notes else None,
        }

    def refresh(self) -> None:
        self.async_write_ha_state()


# ── Buttons ───────────────────────────────────────────────────────────────────

class ClearLastNoteButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Clear Last Note"
    _attr_icon = "mdi:notebook-minus-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        self._coordinator = coordinator
        self._attr_unique_id   = f"{entry.entry_id}_clear_last_note"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        await self._coordinator._notes_store.async_clear_last()
        if self._coordinator._notes_sensor:
            self._coordinator._notes_sensor.refresh()


class ClearAllNotesButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Clear All Notes"
    _attr_icon = "mdi:notebook-remove-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        self._coordinator = coordinator
        self._attr_unique_id   = f"{entry.entry_id}_clear_all_notes"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        await self._coordinator._notes_store.async_clear_all()
        if self._coordinator._notes_sensor:
            self._coordinator._notes_sensor.refresh()


# ── Store bootstrap (called from coordinator setup in __init__.py) ─────────────

async def async_setup_notes_store(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> NotesStore:
    """
    Create and load the NotesStore for this entry.
    Attaches store + a placeholder sensor ref to the coordinator so the
    sensor/button platform setup functions can retrieve them.
    Called from async_setup_entry BEFORE platforms are forwarded.
    """
    store = NotesStore(hass, entry.entry_id)
    await store.async_load()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator._notes_store  = store
    coordinator._notes_sensor = None   # filled in by sensor platform setup

    register_add_note_service(hass)
    return store


def register_add_note_service(hass: HomeAssistant) -> None:
    """Register add_note service once across all entries."""
    if hass.services.has_service(DOMAIN, "add_note"):
        return

    async def handle_add_note(call: ServiceCall) -> None:
        text: str = call.data.get("text", "").strip()
        if not text:
            _LOGGER.warning("add_note called with empty text")
            return
        target = call.data.get("entry_id")
        for eid, coord in hass.data.get(DOMAIN, {}).items():
            if (target is None or eid == target) and hasattr(coord, "_notes_store"):
                await coord._notes_store.async_add(text)
                if coord._notes_sensor:
                    coord._notes_sensor.refresh()
                return
        _LOGGER.warning("add_note: no matching entry for entry_id=%s", target)

    hass.services.async_register(DOMAIN, "add_note", handle_add_note)
    _LOGGER.debug("Registered service %s.add_note", DOMAIN)

# ── MPC identification results persistence ────────────────────────────────────

_MPC_RESULTS_VERSION = 1


class MpcResultsStore:
    """Persists MPC identification results (R², timestamp) across restarts."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, _MPC_RESULTS_VERSION, f"{DOMAIN}.mpc_results.{entry_id}")
        self.r2_temp:         float | None = None
        self.r2_rh:           float | None = None
        self.last_identified: str   | None = None

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.r2_temp         = data.get("r2_temp")
            self.r2_rh           = data.get("r2_rh")
            self.last_identified = data.get("last_identified")

    async def async_save(self, r2_temp: float, r2_rh: float, last_identified: str) -> None:
        self.r2_temp         = r2_temp
        self.r2_rh           = r2_rh
        self.last_identified = last_identified
        await self._store.async_save({
            "r2_temp":         r2_temp,
            "r2_rh":           r2_rh,
            "last_identified": last_identified,
        })


async def async_setup_mpc_results_store(
    hass: HomeAssistant,
    entry,
) -> "MpcResultsStore":
    """Create, load, and attach the MpcResultsStore to the coordinator."""
    from .coordinator import GrowTentCoordinator
    coordinator: GrowTentCoordinator = hass.data[DOMAIN][entry.entry_id]
    store = MpcResultsStore(hass, entry.entry_id)
    await store.async_load()
    coordinator._mpc_results_store = store
    # Restore values into ControlState so sensors show immediately
    if store.r2_temp is not None:
        coordinator.control.mpc_r2_temp = store.r2_temp
    if store.r2_rh is not None:
        coordinator.control.mpc_r2_rh = store.r2_rh
    if store.last_identified is not None:
        coordinator.control.mpc_last_identified = store.last_identified
    return store

