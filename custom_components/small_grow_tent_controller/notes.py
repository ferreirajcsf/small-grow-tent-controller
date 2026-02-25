"""
Grow Journal — persistent dated notes stored in HA's .storage directory.

Storage:  .storage/small_grow_tent_controller.notes.<entry_id>
Schema:   {"notes": [{"ts": "2026-02-24 14:30", "text": "..."}]}

Entities (registered directly via entity_component helpers in __init__.py):
  sensor.<name>_grow_journal      — state = note count, attrs = full list
  button.<name>_clear_last_note   — removes the most recent note
  button.<name>_clear_all_notes   — removes all notes

Service:
  small_grow_tent_controller.add_note
    text:     str   — the note to add (required)
    entry_id: str   — which tent (optional, defaults to first entry)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store

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
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
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
            "notes": list(reversed(notes)),   # newest first
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

    def __init__(self, entry: ConfigEntry, store: NotesStore, sensor: GrowJournalSensor) -> None:
        self._store  = store
        self._sensor = sensor
        self._attr_unique_id   = f"{entry.entry_id}_clear_last_note"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        await self._store.async_clear_last()
        self._sensor.refresh()


class ClearAllNotesButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Clear All Notes"
    _attr_icon = "mdi:notebook-remove-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, store: NotesStore, sensor: GrowJournalSensor) -> None:
        self._store  = store
        self._sensor = sensor
        self._attr_unique_id   = f"{entry.entry_id}_clear_all_notes"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        await self._store.async_clear_all()
        self._sensor.refresh()


# ── Setup (called from __init__.py after all platforms are loaded) ────────────

async def async_setup_notes_for_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """
    Create the notes store, sensor, and buttons for one config entry.
    Uses entity_component helpers so entities appear under the correct device
    without needing a dedicated platform file.
    Called from async_setup_entry in __init__.py after platforms are forwarded.
    """
    store = NotesStore(hass, entry.entry_id)
    await store.async_load()

    sensor = GrowJournalSensor(entry, store)

    # Register sensor via the sensor component's entity adder
    from homeassistant.helpers import entity_component as ec
    sensor_component  = hass.data.get("entity_components", {}).get("sensor")
    button_component  = hass.data.get("entity_components", {}).get("button")

    if sensor_component:
        await sensor_component.async_add_entities([sensor])
    if button_component:
        await button_component.async_add_entities([
            ClearLastNoteButton(entry, store, sensor),
            ClearAllNotesButton(entry, store, sensor),
        ])

    # Attach to coordinator so the service handler can reach this entry's store
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator._notes_store  = store
    coordinator._notes_sensor = sensor

    # Register the add_note service once across all entries
    if not hass.services.has_service(DOMAIN, "add_note"):
        async def handle_add_note(call: ServiceCall) -> None:
            text: str = call.data.get("text", "").strip()
            if not text:
                _LOGGER.warning("add_note called with empty text")
                return
            target = call.data.get("entry_id")
            for eid, coord in hass.data.get(DOMAIN, {}).items():
                if target is None or eid == target:
                    if hasattr(coord, "_notes_store"):
                        await coord._notes_store.async_add(text)
                        coord._notes_sensor.refresh()
                        return
            _LOGGER.warning("add_note: no matching entry found for entry_id=%s", target)

        hass.services.async_register(DOMAIN, "add_note", handle_add_note)
        _LOGGER.debug("Registered service %s.add_note", DOMAIN)
