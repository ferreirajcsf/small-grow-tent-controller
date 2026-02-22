# Changelog

## [0.1.19] - 2026-02-22

### Fixed

- **Circulation fan Off override not working** — setting the circulation mode to `Off` was being silently ignored. The select entity can briefly report `unavailable` after a restart or entity reload, causing `_get_mode()` to fall back to `Auto` and discard the override for that cycle. The control block has been rewritten so the desired state is evaluated and enforced every single poll cycle rather than only when a transition is detected.

- **Circulation fan not recovering on return to Auto** — switching the mode back to `Auto` after a manual `Off` did not turn the fan back on. The previous Auto logic only acted when the fan was off and needed turning on — it had no path to turn the fan on if it had been manually switched off outside the controller. The new logic unconditionally sets the fan to the correct desired state (`on` when enabled, `off` when disabled) every cycle, so it self-corrects within one poll interval (~10 seconds) regardless of how the fan got into the wrong state.

### No Breaking Changes

Update via HACS and restart Home Assistant. No reconfiguration needed.

---

## [0.1.18] - 2026-02-21

### Fixed

- **Suppressed false "sensors unavailable" warning on startup** — on the first poll cycle after HASS restarts, environment sensors are routinely unavailable for a few seconds while Home Assistant initialises its entity registry. The controller now silently skips the warning log message and persistent dashboard notification during this first cycle only. If sensors are still unavailable on the second poll onwards, the warning fires as normal — meaning it only appears for genuine runtime sensor dropouts, not routine restarts.

### No Breaking Changes

Update via HACS and restart Home Assistant. No reconfiguration needed.

---

## [0.1.17] - 2026-02-21

### Changed

- **Growth stages renamed and restructured** — the six growth stages have been updated to better reflect a typical cannabis grow cycle:

  | Stage | Default VPD |
  |---|---|
  | Seedling | 0.70 kPa |
  | Early Vegetative | 0.95 kPa |
  | Late Vegetative | 1.10 kPa |
  | Early Bloom | 1.25 kPa |
  | Late Bloom | 1.45 kPa |
  | Drying | 0.90 kPa |

  Previous stages (`Vegetative`, `Early Flower`, `Mid Flower`, `Late Flower`) have been removed and replaced with `Early Vegetative`, `Late Vegetative`, `Early Bloom`, and `Late Bloom`.

- **Default stage** changed from `Vegetative` to `Early Vegetative`.

### ⚠️ Breaking Change

If you have any Home Assistant automations, scripts, or dashboard cards that reference the old stage names by string (e.g. `option: "Vegetative"` or `option: "Early Flower"`), these will need updating to the new names. On first load after upgrading, if the stored stage state is no longer valid the controller will automatically fall back to `Early Vegetative`.

---

## [0.1.16] - 2026-02-21

### New Features

- **VPD Target number entity** — the VPD target for each growth stage is now a user-adjustable slider (0.40–2.50 kPa, step 0.01 kPa) visible on the device card under Limits. When you change the growth stage, the slider automatically resets to that stage's default on the next controller cycle (~10 seconds). You can nudge it freely at any time without changing stage.

  Default targets per stage (as of v0.1.16, superseded in v0.1.17):
  | Stage | Default VPD |
  |---|---|
  | Seedling | 0.70 kPa |
  | Vegetative | 1.00 kPa |
  | Early Flower | 1.10 kPa |
  | Mid Flower | 1.30 kPa |
  | Late Flower | 1.50 kPa |
  | Drying | 0.90 kPa |

- **VPD Chase switch** — a new "VPD Chase" switch lets you disable the VPD chasing logic entirely. When OFF, the controller operates in limits-only mode during the day: it only acts when temperature or humidity breach their min/max limits, and leaves all devices neutral otherwise. When ON (default), behaviour is identical to previous versions. Useful if you want simple thermostat/humidistat control without the VPD layer.

### Changes

- Removed all references to specific plant types from code comments and documentation. The integration works for any grow tent.
- Schema version bumped to v3. Existing installations migrate automatically — no reconfiguration needed.

### No Breaking Changes

After updating via HACS and restarting Home Assistant, two new entities appear automatically:
- **VPD Target** (number slider) — initialises to your current stage's default
- **VPD Chase** (switch) — defaults to ON

All existing entity IDs, stored states, and settings are preserved.

---

## [0.1.15] - 2026-02-21

### New Features
- **Last Action sensor** — shows what the controller last did and when (e.g. `Exhaust ON · temp_above_max @ 14:32:01`).
- **Sensors Unavailable binary sensor** — turns ON when environment sensors drop off or return invalid readings.
- **Persistent notification on sensor dropout** — fires when sensors go missing, auto-dismisses on recovery.

### Improvements
- `coordinator.py` refactored into focused sub-methods for readability and maintainability.

---

## [0.1.14] - 2026-02-20

### Fixed
- Removed broken `device.py` dead-code stub.
- `device_info` added to all entity platforms — all entities now group under one device card.
- Heater on-time tracking fixed.
- `blocking=True` on heater safety trips.
- Migration guard for unknown schema versions.
- Hardcoded personal entity IDs removed from defaults.
- Light schedule default mismatch fixed.
- `state_class` added to VPD and dew point sensors.

### Changed
- Debug sensors hidden by default (`entity_registry_enabled_default = False`).

---

## [0.1.13] - 2025-XX-XX

- Initial feature-complete release with VPD chase, night mode, drying mode, heater pulse plan, exhaust safety override, per-device manual overrides, and config flow v2.
