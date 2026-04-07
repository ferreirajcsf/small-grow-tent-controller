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



# ── Toggle counter persistence ────────────────────────────────────────────────

_TOGGLE_STORE_VERSION = 1


class ToggleCounterStore:
    """Persists cumulative device toggle counters across HA restarts.

    Counters are incremented in-memory every time a device is switched and
    flushed to .storage asynchronously.  The flush is triggered after every
    toggle so the data is always fresh, but the write is non-blocking so it
    never delays the poll cycle.
    """

    _KEYS = ("heater", "exhaust", "humidifier", "dehumidifier")

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(
            hass, _TOGGLE_STORE_VERSION,
            f"{DOMAIN}.toggle_counters.{entry_id}"
        )
        self.heater:       int = 0
        self.exhaust:      int = 0
        self.humidifier:   int = 0
        self.dehumidifier: int = 0

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self.heater       = int(data.get("heater",       0))
            self.exhaust      = int(data.get("exhaust",      0))
            self.humidifier   = int(data.get("humidifier",   0))
            self.dehumidifier = int(data.get("dehumidifier", 0))

    async def async_save(self) -> None:
        await self._store.async_save({
            "heater":       self.heater,
            "exhaust":      self.exhaust,
            "humidifier":   self.humidifier,
            "dehumidifier": self.dehumidifier,
        })

    def increment(self, device: str) -> None:
        """Increment one counter in memory.  Caller must schedule async_save."""
        if device == "heater":
            self.heater += 1
        elif device == "exhaust":
            self.exhaust += 1
        elif device == "humidifier":
            self.humidifier += 1
        elif device == "dehumidifier":
            self.dehumidifier += 1


async def async_setup_toggle_counter_store(
    hass: HomeAssistant,
    entry,
) -> "ToggleCounterStore":
    """Create, load, and attach the ToggleCounterStore to the coordinator."""
    from .coordinator import GrowTentCoordinator
    coordinator: GrowTentCoordinator = hass.data[DOMAIN][entry.entry_id]
    store = ToggleCounterStore(hass, entry.entry_id)
    await store.async_load()
    coordinator._toggle_store = store
    # Seed ControlState counters from persisted values so sensors show correct
    # totals immediately on startup — before any new toggles occur.
    coordinator.control.heater_toggles       = store.heater
    coordinator.control.exhaust_toggles      = store.exhaust
    coordinator.control.humidifier_toggles   = store.humidifier
    coordinator.control.dehumidifier_toggles = store.dehumidifier
    return store


# ── VPD deadband 24-hour rolling window ───────────────────────────────────────

_VPD_BAND_STORE_VERSION = 1


class VpdBandStore:
    """Persists a 24-bucket (one per hour) rolling window of VPD deadband polls.

    Each bucket stores {"in": N, "total": N} for one clock hour.
    The 24h percentage is sum(in) / sum(total) across all buckets.
    Buckets are keyed 0–23 by hour-of-day; the current hour's bucket is
    cleared at the start of each new hour so old data ages out naturally.

    This is much lighter than storing 8,640 individual poll results, gives
    exact 24h accuracy to within one hour, and survives HA restarts.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(
            hass, _VPD_BAND_STORE_VERSION,
            f"{DOMAIN}.vpd_band.{entry_id}"
        )
        # buckets[h] = {"in": int, "total": int, "hour_ts": int (unix hour stamp)}
        self.buckets: dict[int, dict] = {}
        self._current_hour_ts: int = 0   # unix timestamp of the current hour

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data and isinstance(data.get("buckets"), dict):
            self.buckets = {int(k): v for k, v in data["buckets"].items()}
        self._current_hour_ts = self._hour_ts_now()

    async def async_save(self) -> None:
        await self._store.async_save({"buckets": self.buckets})

    @staticmethod
    def _hour_ts_now() -> int:
        """Current time truncated to the hour, as a unix timestamp."""
        import time as _time
        t = int(_time.time())
        return t - (t % 3600)

    def record(self, in_band: bool) -> None:
        """Record one poll result. Caller schedules async_save."""
        now_hour_ts = self._hour_ts_now()

        # On hour boundary: advance and clear any bucket older than 23 hours
        if now_hour_ts != self._current_hour_ts:
            self._current_hour_ts = now_hour_ts

        # Expire buckets strictly older than 24 hours
        cutoff = now_hour_ts - 24 * 3600
        self.buckets = {
            k: v for k, v in self.buckets.items()
            if v.get("hour_ts", 0) > cutoff
        }

        # Current bucket key = hour index 0–23
        hour_key = (now_hour_ts // 3600) % 24
        bucket = self.buckets.get(hour_key)
        if bucket is None or bucket.get("hour_ts", 0) != now_hour_ts:
            # New hour — start fresh bucket
            bucket = {"in": 0, "total": 0, "hour_ts": now_hour_ts}
            self.buckets[hour_key] = bucket

        bucket["total"] += 1
        if in_band:
            bucket["in"] += 1

    @property
    def pct_24h(self) -> float | None:
        """Percentage of polls in band over the last 24 hours. None if no data."""
        now_hour_ts = self._hour_ts_now()
        cutoff = now_hour_ts - 24 * 3600
        total = sum(v["total"] for v in self.buckets.values() if v.get("hour_ts", 0) > cutoff)
        in_b  = sum(v["in"]    for v in self.buckets.values() if v.get("hour_ts", 0) > cutoff)
        if total == 0:
            return None
        return round(in_b / total * 100.0, 1)

    @property
    def hours_of_data(self) -> int:
        """How many distinct hours of data are in the window."""
        now_hour_ts = self._hour_ts_now()
        cutoff = now_hour_ts - 24 * 3600
        return sum(1 for v in self.buckets.values() if v.get("hour_ts", 0) > cutoff)


async def async_setup_vpd_band_store(
    hass: HomeAssistant,
    entry,
) -> "VpdBandStore":
    """Create, load, and attach the VpdBandStore to the coordinator."""
    from .coordinator import GrowTentCoordinator
    coordinator: GrowTentCoordinator = hass.data[DOMAIN][entry.entry_id]
    store = VpdBandStore(hass, entry.entry_id)
    await store.async_load()
    coordinator._vpd_band_store = store
    return store
