# Changelog

## [0.1.36] - 2026-03-23

### Changed

- **Night Mode: "VPD Chase (No Heater)" replaces Heater Mode "Night Off"** — the option to exclude the heater from VPD chasing at night has been moved from the Heater Mode device dropdown into the Night Mode selector in Tuning/Safety, where it logically belongs. The Heater Mode dropdown reverts to its original three options (`Auto`, `On`, `Off`).

  The Night Mode selector now has three options:

  | Option | Behaviour |
  |---|---|
  | **Dew Protection** | Unchanged — heater pulses to dew + margin, humidifier off, exhaust follows stage profile |
  | **VPD Chase** | Full VPD chase at night + dew-point floor + stage exhaust profile |
  | **VPD Chase (No Heater)** | Same as VPD Chase but heater excluded from chasing VPD; dew-point protection still fires unconditionally |

### Fixed

- Heater Mode dropdown no longer shows a `Night Off` option that had no effect in most modes and caused confusion.

---

## [0.1.35] - 2026-03-23

### Added

- **Heater Mode: Night Off option** — the Heater Mode dropdown now includes a fourth option, `Night Off`, alongside the existing `Auto`, `On`, and `Off`.

  When `Night Off` is selected and the Night Mode is set to **VPD Chase**:
  - The heater is **excluded from VPD chasing** — it will not turn on or off in pursuit of the VPD target.
  - **Dew-point protection still fires** — if temperature falls to dew point + margin, the heater turns on regardless. Condensation protection is never disabled.
  - In all other modes (Dew Protection night, daytime, drying), `Night Off` behaves identically to `Auto` — the heater is used normally.

  This is useful if you want humidity and exhaust to drive VPD at night without the heater cycling, while still having a safety net against condensation.

---

## [0.1.34] - 2026-03-22

### Added

- **Night Mode select** — a new dropdown in the Tuning/Safety section lets you choose how the controller behaves during the night (light-off) window:

  - **Dew Protection** *(default — existing behaviour unchanged)* — heater pulses proportionally to keep temperature above dew point + margin. Humidifier is forced off. Dehumidifier runs if RH is above the max limit. Exhaust follows the per-stage night profile (on/auto).
  - **VPD Chase** — runs the same VPD chase logic as daytime (heater, exhaust, humidifier, dehumidifier all work toward VPD/temp/RH targets). A dew-point floor is always enforced: if VPD chase would leave the heater off but temperature is at or below dew + margin, the heater is turned on regardless. The per-stage exhaust night profile is also still applied on top of the VPD chase exhaust decision.

  Switching to Dew Protection at any time restores the original night behaviour with no other changes required.

---

## [0.1.33] - 2026-03-12

### Fixed

- **Heater safety shutoff when sensors become unavailable** — previously, if the temperature/humidity sensors dropped out while the heater was running, the controller would enter `waiting_for_sensors` mode and return early every poll cycle, leaving the heater on indefinitely with no feedback. The tent could overheat without any intervention until sensors recovered or the user noticed manually.

  The controller now immediately turns the heater off (blocking call) the moment sensors become unavailable, and logs a warning. The heater will resume normal automatic control once all sensors report valid readings again.

---

## [0.1.32] - 2026-03-03

### Fixed

- **Circulation fan Auto mode now correctly handles drying and disabled states** — previously, when the circulation fan mode was set to "Auto", it would stay on even during drying mode and when the controller was disabled. It now turns off in both of those cases. During normal operation (day and night) it remains on continuously, which is beneficial for temperature equalisation, boundary-layer disruption, and mould prevention. Manual On/Off overrides continue to work as before.

---

## [0.1.31] - 2026-02-26

### Fixed

- **VPD chase exhaust fallback** — when no dehumidifier is configured, the VPD chase logic now correctly falls back to the exhaust fan as the humidity-reduction device. Previously, the three branches that needed to reduce humidity (`vpd_low: temp above target`, `vpd_low: temp at target`, and `vpd_inband: rh above target`) all called `_dehumidifier_on` and did nothing when no dehumidifier was configured, causing the controller to appear frozen even when VPD was well outside the deadband.

  A new `_reduce_humidity` helper encapsulates the fallback logic: use the dehumidifier if one is configured, otherwise turn on the exhaust fan. A matching `_stop_reducing_humidity` helper is also added for symmetry.

---

## [0.1.30] - 2026-02-26

### Added

- **Local brand images** — `icon.png` and `logo.png` moved into a new `brand/` subfolder inside the integration directory, as required by Home Assistant 2026.3+. Custom integrations can now ship their own brand images directly without submitting to the `home-assistant/brands` repository. Local images automatically take priority over the CDN.

---

## [0.1.29] - 2026-02-26

### Added

- **VPD Congruence card in the Targets section** — a new `mushroom-template-card` sits at the top of the Targets panel and instantly shows whether the three target values (VPD Target, Target Temp, Target RH) are mutually consistent.
  - Shows a green ✅ and "Targets are congruent" when the implied VPD (derived from Target Temp + Target RH) is within the deadband of the VPD Target.
  - Shows an orange ⚠️ warning with a suggested RH correction when a conflict is detected, replacing the need to read two separate conditional conflict cards.
  - Uses the existing `sensor.small_grow_tent_controller_target_conflict`, `sensor.small_grow_tent_controller_target_vpd_implied`, and `sensor.small_grow_tent_controller_target_implied_rh` sensors — no new backend entities required.
- **Dashboard screenshot updated** — `images/screenshot_v0.1.29.png` added; README example-dashboard section now points to this file.

---

## [0.1.28] - 2026-02-25

### Removed

- **VPD Drives Temperature mode** — removed entirely. The mode, its switch entity, its two ramp-limit number sliders (Temp Ramp Fast Limit, Temp Ramp Slow Limit), and its diagnostic sensors (VPD Driven Temp Target, VPD Driven Ideal Temp, VPD Driven Temp Clamped, VPD Driven Ramp Limited) have all been removed. The VPD Chase mode with Target Temperature and Target Humidity remains the standard day-time control strategy.

### Fixed

- **Exhaust safety is now a true system-wide safety** — previously the Exhaust Safety Override only blocked manual Off overrides. The check is now applied inside the low-level `_exhaust_off_if_on` helper, meaning every code path that tries to turn the exhaust off (hard limits, night mode, VPD chase, drying mode, manual override) is gated through the safety check. When the safety is enabled and temperature or humidity exceeds the configured thresholds, any attempt to turn the exhaust off is silently blocked and logged with a `[SAFETY: blocked_off]` suffix in the `debug_exhaust_reason` sensor.

### ⚠️ Breaking Changes

The following entities are removed. Update any automations, dashboard cards, or scripts that reference them before upgrading:

- `switch.<n>_vpd_drives_temperature`
- `sensor.<n>_vpd_driven_temp_target`
- `number.<n>_temp_ramp_fast_limit`
- `number.<n>_temp_ramp_slow_limit`
- `sensor.<n>_debug_vpd_driven_ideal_temp`, `..._clamped`, `..._ramp_limited`

---

## [0.1.27] - 2026-02-25

### New Features

- **Grow Journal** — built-in timestamped note log persisted in HA's `.storage` directory.
  - New `sensor.<n>_grow_journal` entity — state is the note count; `notes` attribute holds the
    full list (newest first) for dashboard rendering
  - New `button.<n>_clear_last_note` and `button.<n>_clear_all_notes` buttons
  - New `small_grow_tent_controller.add_note` service (accepts `text` + optional `entry_id`)
  - Dashboard: add notes from a text input field, view the full log as a formatted markdown list
    in the Grow Cycle section of the Status view
  - Requires one HA Text helper named **Grow Note Input** (`input_text.grow_note_input`)

---

## [0.1.26] - 2026-02-24

### Bug Fixes

- **Exhaust fan forced on at night** — All grow stages (Early Vegetative, Late Vegetative,
  Early Bloom, Late Bloom) were incorrectly forcing the exhaust fan on throughout the entire
  night period. These stages now use `auto` mode, meaning the exhaust only runs at night when
  needed for dew-point protection. Drying stage retains forced-on behaviour as intended.

---

## [0.1.25] - 2026-02-22

### New Features

- **VPD Drives Temperature mode** — a new control strategy for setups with no humidity control (heater only). When enabled, the VPD Target becomes the master value. Every 10 seconds the controller reads live RH (which it cannot control), solves for the air temperature that would produce the target VPD at that RH, and uses the heater and exhaust to chase that calculated temperature. The Target Temperature and Target Humidity sliders become fallback/reference values only in this mode.

  **Auto-detection:** the mode activates automatically when no humidifier and no dehumidifier are configured. Users with humidity control get the original chase behaviour by default. Either way, the new **VPD Drives Temperature** switch lets you override in either direction.

- **Temperature ramp limiting** — two new sliders prevent the calculated target from jumping suddenly when RH changes quickly:
  - **Ramp Fast Limit** (°C per 10-min window, default 0.5°C) — prevents sudden spikes
  - **Ramp Slow Limit** (°C per hour, default 2.0°C) — prevents sustained creep
  Both appear in the Tuning section only when VPD Drives Temperature is enabled.

- **New sensor: VPD Driven Temp Target** — shows the temperature the controller is currently chasing based on live RH and target VPD. Visible in the Calculations section when the mode is active.

### Technical details

- Target temperature is solved by bisection (30 iterations, <0.01°C precision) over the same `VPD_leaf = SVP(leaf) - RH/100 × SVP(air)` formula used everywhere else in the integration.
- Calculated target is always clamped to [min_temp, max_temp] hard limits silently — no action required.
- Ramp history is kept in memory and resets on HA restart (intentional — avoids stale ramp anchors after a long downtime).

### No Breaking Changes

Update via HACS and restart. One new switch entity and two new sensor entities will appear. If you have no humidifier or dehumidifier configured, the VPD Drives Temperature switch will turn itself on automatically on first install.

---

## [0.1.24] - 2026-02-22

### New Features

- **Target conflict detection** — the controller now computes the VPD that would result from your Target Temperature + Target Humidity settings (using the same leaf offset formula used for live VPD), and compares it to your VPD Target. Three new diagnostic sensors are exposed:
  - **Target VPD (Implied)** — the VPD your temp + RH targets would actually produce
  - **Target Conflict** — deviation as a percentage (positive = implied VPD too low, negative = too high)
  - **Implied RH for Target VPD** — the RH you would need at Target Temp to actually hit your VPD Target

- **Dashboard warning cards** — two conditional cards appear in the Limits & Targets section when the conflict exceeds ±15%. Each card tells the user which direction the conflict is, what VPD their current targets imply, and what RH they should set to resolve it. The cards disappear automatically once targets are consistent.

### No Breaking Changes

Update via HACS and restart Home Assistant. Three new sensor entities will appear on your device.

---

## [0.1.23] - 2026-02-22

### New Features

- **Target Temperature and Target Humidity sliders** — two new number entities added alongside the existing VPD Target:
  - **Target Temperature** (°C) — the temperature the controller chases during VPD chase mode
  - **Target Humidity** (% RH) — the humidity the controller nudges toward when VPD is in band
  Both reset automatically to stage defaults when the stage changes, and can be adjusted freely at any time — identical behaviour to the VPD Target slider.

  Default targets per stage:

  | Stage | Target Temp | Target RH |
  |---|---|---|
  | Seedling | 24°C | 70% |
  | Early Vegetative | 25°C | 60% |
  | Late Vegetative | 26°C | 55% |
  | Early Bloom | 26°C | 50% |
  | Late Bloom | 25°C | 45% |
  | Drying | 21°C | 55% |

### Fixed

- **VPD chase driving temperature to max limit** — the controller was using `max_temp` as its heating ceiling, causing it to push temperature to the top of the safety range regardless of VPD. The VPD chase logic has been rewritten to prioritise reaching **Target Temperature** first (using heater/exhaust), then use the humidifier/dehumidifier to address RH. When VPD is in band, the controller now fine-tunes RH toward Target Humidity within a 2% deadband.

### ⚠️ Breaking Change

After updating, two new entities will appear on your device card: **Target Temperature** and **Target Humidity**. These initialise to the stage defaults above. No existing entities are affected.

### No Breaking Changes to existing entities

Update via HACS and restart Home Assistant. No reconfiguration needed.

---

## [0.1.22] - 2026-02-22

### Fixed

- **Circulation fan control fully rebuilt** — circulation is now wired up identically to all other devices end to end. On/Off overrides are handled in `_apply_forced_modes` which nulls out `ctx.circ_eid` to prevent any further action downstream. The Auto case uses new `_circ_on` / `_circ_off` atomic helpers (same pattern as `_humidifier_on`, `_dehumidifier_off`, etc.) that read and update `ctx.circ_on` directly — no more raw `_switch_is_on` reads that could disagree with the context state. The fan will turn on within one poll cycle (~10 seconds) when switched back to Auto, regardless of how it was turned off.

### Changed

- **README** — dashboard screenshot moved to the Example Dashboard section where it is more relevant.

### No Breaking Changes

Update via HACS and restart Home Assistant. No reconfiguration needed.

---

## [0.1.20] - 2026-02-22

### Fixed

- **Circulation fan override and Auto not working reliably** — the circulation fan was handled by a separate inline block outside the standard device override pipeline (`_apply_forced_modes`). This meant On/Off overrides were not enforced with the same reliability as other devices, and switching back to Auto after a manual off did not reliably restore the fan. Circulation is now fully integrated into `_apply_forced_modes` alongside the heater, humidifier, and dehumidifier — On/Off overrides null out `ctx.circ_eid` exactly like other devices, and the Auto case enforces the correct state every poll cycle after forced modes have run.

- **Device mode and stage selectors not restoring state correctly after restart** — `DeviceModeSelect` and `StageSelect` both use `RestoreEntity` to persist their last value across restarts. However, neither was calling `async_write_ha_state()` after restoring the value in `async_added_to_hass()`. This meant the entity's internal state was correctly restored, but the HA state machine was never updated with it. As a result, `_get_mode()` in the coordinator — which reads from the HA state machine — would see `unknown` instead of the restored value and silently fall back to `Auto`, causing device overrides and the selected stage to be ignored until the user manually changed them again after every restart.

  This was the root cause of the circulation fan override not taking effect after a restart. The fix adds `async_write_ha_state()` to both `async_added_to_hass()` methods so the state machine is always in sync with the restored internal state from the first coordinator poll onwards.

### No Breaking Changes

Update via HACS and restart Home Assistant. No reconfiguration needed.

---

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
