# Changelog

## [0.1.15] - 2026-02-21

### New Features

- **Last Action sensor** — a new `Last Action` sensor (always visible, not a debug entity) shows exactly what the controller last did and when, e.g. `Exhaust ON · hard_limit: temp_above_max @ 14:32:01`. Makes it easy to see at a glance what changed without enabling debug sensors.

- **Sensors Unavailable binary sensor** — a new `Sensors Unavailable` binary sensor (device class: Problem) turns ON when one or more environment sensors are missing or returning invalid readings. Use it in automations or dashboards to alert on sensor dropouts.

- **Persistent notification on sensor dropout** — when sensors go unavailable, a persistent notification is created in the HA notification bell explaining what happened and how to fix it. The notification is automatically dismissed when all sensors recover.

### Improvements

- **`coordinator.py` refactored** — the monolithic `_apply_control` method (~400 lines) has been split into focused, named sub-methods: `_apply_drying_mode`, `_apply_night_mode`, `_apply_heater_pulse`, `_apply_day_hard_limits`, `_apply_vpd_chase`, `_apply_forced_modes`, `_apply_heater_safety`, and a set of atomic device helpers (`_heater_off`, `_exhaust_on_if_off`, etc.). Logic is identical — this is purely a readability and maintainability improvement.

### No Breaking Changes

All entity unique IDs and stored states are preserved. After updating via HACS, restart Home Assistant. The two new entities (`Last Action` sensor and `Sensors Unavailable` binary sensor) will appear automatically in the device card.

---

## [0.1.14] - 2026-02-20

### Fixed
- **Removed `device.py`** — dead-code stub that referenced undefined constants and caused an import error on load.
- **`device_info` added to all entity platforms** — all entities now group under a single device card in the HA UI.
- **Heater on-time tracking fixed** — max-run safety timer now captures hardware state before forced overrides are applied.
- **`blocking=True` on heater safety trips** — force-off on max-run lockout now waits for confirmation.
- **Migration guard for unknown versions** — `async_migrate_entry` now returns `False` for unrecognised schema versions.
- **Hardcoded personal entity IDs removed** — config flow no longer pre-fills with the author's own entity IDs.
- **Light schedule default mismatch fixed** — `time.py` defaults now match the coordinator fallbacks exactly.
- **`state_class` added to VPD and dew point sensors** — both sensors now log to long-term statistics.

### Changed
- **Debug sensors hidden by default** — all `debug_*` sensors use `entity_registry_enabled_default = False`.
- **`VERSION` constant added to `const.py`** — used by `device_info_for_entry` for `sw_version`.

---

## [0.1.13] - 2025-XX-XX

- Heater max run time safety with configurable lockout.
- Exhaust safety override switch.
- Per-device manual override selects (Auto / On / Off).
- "Return All Devices to Auto" button entity.
- Humidifier and dehumidifier support.
- Night-mode dewpoint protection with stage-specific exhaust profiles.
- VPD-chase day mode with hard-limit and drying-mode overrides.
- Heater pulse plan (proportional on/off timing).
- Config flow v2 with two-step setup.
- Entry migration from v1 → v2.
