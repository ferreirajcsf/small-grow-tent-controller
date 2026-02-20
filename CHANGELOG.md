# Changelog

## [0.1.14] - 2026-02-20

### Fixed
- **Removed `device.py`** — dead-code stub that referenced undefined constants (`CONF_NAME`, `DEFAULT_NAME`, `INTEGRATION_VERSION`) and would cause an import error on load. Its `device_info_for_entry` helper has been reimplemented correctly in `__init__.py`.
- **`device_info` added to all entity platforms** (`sensor`, `switch`, `number`, `select`, `time`, `button`, `binary_sensor`). All entities now group under a single device card in the HA UI, named after the config entry title. Multiple tent instances each get their own device.
- **Heater on-time tracking fixed** — the `heater_on_since` timestamp is now captured from the real hardware switch state *before* forced overrides are applied, preventing the max-run safety timer from being skipped when a manual override is active.
- **`blocking=True` on heater safety trips** — the max-run lockout force-off call now uses `blocking=True` to guarantee the switch command completes before control logic continues. All other switch calls remain `blocking=False` for performance.
- **Migration guard for unknown versions** — `async_migrate_entry` now explicitly returns `False` for unrecognised schema versions instead of silently returning `True`, preventing silent data corruption from future migration bugs.
- **Hardcoded personal entity IDs removed from `const.py`** — `DEFAULTS` now uses empty strings so the config flow no longer pre-fills with the author's own entity IDs for new installations.
- **Light schedule default mismatch fixed** — `time.py` defaults (`light_on=09:00`, `light_off=21:00`) now match the coordinator fallbacks exactly, eliminating a one-hour discrepancy on first boot.
- **`state_class` added to VPD and dew point sensors** — both sensors now have `SensorStateClass.MEASUREMENT` so HA logs them in the long-term statistics database.

### Changed
- **Debug sensors hidden by default** — all `debug_*` sensors are created with `entity_registry_enabled_default = False`. They remain available and can be enabled individually via Settings → Entities. This keeps the default dashboard clean.
- **`VERSION` constant added to `const.py`** — used by `device_info_for_entry` for the `sw_version` field.
- **Light schedule defaults unified** — a module-level `_DEFAULT_LIGHT_ON` / `_DEFAULT_LIGHT_OFF` constant in `coordinator.py` is the single source of truth for fallback schedule times.

---

## [0.1.13] - 2025-XX-XX

- Heater max run time safety feature with configurable lockout.
- Exhaust safety override switch (prevents force-off above temp/RH thresholds).
- Per-device manual override selects (Auto / On / Off) for all controlled devices.
- "Return All Devices to Auto" button entity.
- Humidifier and dehumidifier support added to all control modes.
- Night-mode dewpoint protection with stage-specific exhaust profiles.
- VPD-chase day mode with hard-limit and drying-mode overrides.
- Heater pulse plan (proportional on/off timing based on temperature error).
- Config flow v2 with two-step setup (device selection → entity assignment).
- Entry migration from v1 → v2.
