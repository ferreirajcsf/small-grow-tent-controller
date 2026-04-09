## [0.1.76] - 2026-04-09

### Changed

- **Completed decide/apply refactor (Phase 2)** — the controller now has a clean
  separation between *deciding* what to do and *doing* it, consistently enforced
  across all control modes.

  **Architecture after this release:**

  Every poll cycle follows the same four-step pattern:

  ```
  1. build_ctx        — read sensors, entities, config into an immutable _Ctx
  2. pre-decide       — safety trips and manual overrides (may return early)
  3. decide           — all _decide_* methods: pure functions, no I/O, return ControlDecision
  4. apply            — _apply_decision: the ONLY place _async_switch is called (normal flow)
  ```

  The three direct `_async_switch` calls that remain outside `_apply_decision` are
  all intentional safety exceptions — heater shutdown on sensor dropout and heater
  max-run-time trip — and are documented as such. They bypass the decision layer
  on purpose: a blocking safety trip must complete before the rest of the cycle
  runs, and routing it through a `ControlDecision` would add fragile indirection
  with no benefit.

  **What changed specifically:**

  - `_decide_heater_pulse` is now a plain `def` (was `async def`). It does no I/O —
    it only reads and advances the pulse/cooldown timer state and returns a
    `ControlDecision`. Making it `async` was misleading and caused a redundant
    event-loop suspension on every night-mode cycle. The `await` at its call site
    in `_decide_night_mode` is removed accordingly.

  - `_apply_decision` now emits a structured `DEBUG` log line before any switch
    fires, listing every device that is about to change state with its direction
    and reason string. Enable debug logging for this integration to see a complete
    decision trace:

    ```yaml
    logger:
      logs:
        custom_components.small_grow_tent_controller: debug
    ```

    Example output:
    ```
    [Tent] decision: mode=vpd_chase heater=OFF (vpd_inband -> heater_off) | exhaust=ON (vpd_high: temp ok -> exhaust_on)
    ```

    The log is zero-cost when DEBUG is not enabled — the `isEnabledFor` guard
    skips all string formatting.

### Why this matters

- **Debugging**: every decision is logged in one place before hardware is touched.
  If a device does something unexpected, the reason is in the log with the cycle
  that caused it — no need to instrument `_async_switch` or add print statements.
- **Testing**: all `_decide_*` methods are pure functions that take a `_Ctx` and
  return a `ControlDecision`. They can be unit-tested without mocking any HA
  internals or hardware.
- **Future upgrades**: adding a new control mode means writing a `_decide_*`
  method and plugging it into the dispatch table. No risk of accidentally calling
  `_async_switch` in the wrong place.

## [0.1.75] - 2026-04-09

### Fixed

- **Bug: heater max-run-time safety never fired via decide/apply path** — `_apply_decision`
  (the Phase 1 refactored actuation point) was not updating `heater_on_since` when it turned
  the heater on. The safety trip in `_apply_heater_safety` checks
  `(now - heater_on_since).total_seconds() >= heater_max_run_s`, but because `heater_on_since`
  was only set by the legacy atomic helper `_heater_on_if_allowed` (no longer called for most
  control modes), the timer never started and the heater could run indefinitely regardless of
  the **Heater Max Run Time** setting. `_apply_decision` now sets `heater_on_since = now` when
  `dec.heater is True` and clears it to `None` when `dec.heater is False`, matching the
  behaviour of the legacy path.

- **`vpd_polls_total` was written to the data dict every poll but never surfaced as a sensor
  entity** — the key was populated in `_update_observability` and initialised in
  `_async_update_data`, but missing from the `SENSORS` list in `sensor.py`, making it
  invisible in the HA UI. Added as a hidden diagnostic sensor (`VPD Polls Total`), consistent
  with the other observability sensors.

## [0.1.74] - 2026-04-05

### Added
- **Observability: VPD % In Target Band sensor** — tracks the percentage of 10-second
  poll cycles where VPD was within the configured deadband of the target. Resets on
  restart; HA long-term statistics accumulate the trend over days and weeks.
  `sensor.xxx_vpd_pct_in_target_band`
- **Observability: VPD Out-of-Band Duration sensor** — shows how many seconds VPD has
  been continuously outside the deadband in the current streak. Resets to 0 when VPD
  returns to band. `sensor.xxx_vpd_out_of_band_duration`
- **Observability: device toggle counters** — four `TOTAL_INCREASING` diagnostic sensors
  count cumulative on/off transitions for heater, exhaust, humidifier, and dehumidifier
  since last restart. Because they use `SensorStateClass.TOTAL_INCREASING`, HA natively
  computes toggles/hour or toggles/day via the statistics graph — no extra configuration
  needed. Hidden by default; enable via Settings → Entities.
- **Observability: structured cycle log** — every poll cycle emits one `INFO` log line
  containing controller state, sensor readings, VPD vs target, device states, control
  mode, and the primary reason string. Identical consecutive lines are suppressed; a
  heartbeat is emitted every ~10 minutes if nothing changes. Format:
  `[Tent] DAY | 24.1°C 62.3% 1.120kPa | target=1.15kPa 87.3%_in_band | heat=OFF exh=ON hum=OFF deh=OFF | vpd_chase vpd_high: temp ok -> reduce_humidity`

### Fixed
- **Bug 1** — Orphaned section-header comment indentation.
- **Bug 2** — `mpc_a_bias_day` default mismatch (0.250 → 0.180).
- **Bug 3** — `GrowTime` missing `async_write_ha_state()` after restore.
- **Bug 4 / hotfix** — `NameError` on `heater_on_actual` when controller disabled.
- **Bug 5** — Removed dead-code `_mpc_simulate` and `_mpc_score` methods.
- **Bug 6** — Per-sensor display values now use filtered readings.
- **Bug 7** — `get_significant_states` moved to thread executor.
- **Bug 8** — `rh_above_max` branch inconsistent `>` vs `>=` guard.
- **Bug 9** — `ControlState` dict fields now use `field(default_factory=dict)`.
- **Disturbance entity name collision** — switch renamed to **Trigger Disturbance Hold**,
  binary sensor renamed to **Disturbance Hold Active**.

### Repository / docs
- **README** — corrected entity list, fixed stale MPC debug sensor note, fixed
  "four sensor entity IDs" wording.
- **manifest.json** — added missing `homeassistant: "2024.1.0"` minimum version field.
- **hacs.json** — removed country restriction.

## [0.1.73] - 2026-04-05

### Fixed
- Bug fixes and repository tidy-up. See v0.1.74 changelog for full details — these
  fixes were originally tagged as 0.1.73 before observability features were added.

## [0.1.72] - 2026-04-04

### Fixed

- **Migration chain broken for v1 entries** — users upgrading from config schema v1 would have their migration stop at v2, never reaching v3–v5. This meant they were missing the `ambient_temp`, `ambient_rh`, and `weather_entity` fields (added in v3→v4) and the sensor slot rename from `canopy_temp`/`top_temp` to `temp_sensor_1`/`temp_sensor_2` (added in v4→v5), leaving the integration stuck in `waiting_for_sensors` after upgrade. The v2, v3, and v4 migration blocks now fall through correctly to the next step instead of returning early.

- **Disturbance detection: delta computed against itself on first poll after hold** — `prev_avg_temp` and `prev_avg_rh` were written twice per poll cycle: once inside the disturbance-active block before it returned early, and again at the bottom of the control method. The premature write inside the disturbance block meant the first poll after a hold ended was always comparing the current reading against itself (delta = 0), suppressing auto-detection for that cycle. The redundant early write has been removed; only the single write at the bottom of the cycle remains.

- **Disturbance neutral block did not update hold timers** — when the disturbance hold switched devices off, `last_heater_change`, `last_exhaust_change`, `last_humidifier_change`, and `last_dehumidifier_change` were not updated. This meant hold times were not respected on the first poll after disturbance recovery — the controller could immediately re-toggle any device it had just switched off. Each device's change timestamp is now correctly updated when it is switched off during a disturbance hold.

- **RLS debug log computed innovation with post-update parameters** — the `innovation_t` and `innovation_r` values logged at debug level were computed using `ctrl.rls_theta_t` / `ctrl.rls_theta_r` *after* those fields had already been overwritten with the new parameter estimates. The logged values were therefore not the true pre-update prediction error. Both innovations are now captured before the RLS update runs and the correct pre-update values are logged.

- **MPC horizon fallback default was 18 instead of 3** — if the `mpc_horizon_steps` number entity was unavailable during HA startup (before entities are restored), the coordinator fell back to a default of 18. The number entity's configured maximum is 6, and `_apply_mpc_day` / `_apply_night_mpc` clamp to 6 — so no incorrect output occurred, but the clamp warning fired every cycle for ~60 seconds during startup. The fallback now matches the entity default of 3.

- **MPC model identification accessed `hass` from a worker thread** — `get_states_sync` was a closure that captured `self.hass` and called `get_significant_states(self.hass, ...)` inside `async_add_executor_job`. Accessing HA's state machine from a worker thread is not thread-safe. Recorder history is now fetched in full on the event loop before the executor job is dispatched. `_run_identification` receives only plain Python data (a pre-fetched `dict[str, list[tuple[float, str]]]`) and never touches `hass` from the worker thread.

- **`NotesStore` used timezone-naive timestamps** — journal entry timestamps were generated with `datetime.now().strftime(...)`, producing local-naive datetimes that could be wrong if HA's configured timezone differs from the OS timezone. Timestamps now use `dt_util.as_local(dt_util.utcnow())`, consistent with the rest of the integration.

- **Disabled controller did not apply exhaust safety as a baseline** — when the controller was disabled and the exhaust override was set to `Off`, the code already checked the safety thresholds to keep the exhaust on — but the comment and intent were ambiguous about whether this was gated on the `ExhaustSafetyOverride` switch being enabled. The behaviour has been clarified and hardened: the threshold check in the disabled block is an **unconditional baseline safety** that applies regardless of whether `ExhaustSafetyOverride` is on or off. A tent can overheat whether the controller is running or not.

### Removed

- **Dead `_stop_reducing_humidity` helper** — this method (which turned off the dehumidifier or exhaust fan to mirror `_reduce_humidity`) was defined in the coordinator but never called. All call sites used `_dehumidifier_off` or `_exhaust_off_if_on` directly. Removed to eliminate dead code.

### Changed

- **Config flow device switch selectors now restricted to `switch` domain** — the entity selectors for heater, exhaust, humidifier, dehumidifier, circulation, and light were previously configured with `domain=["switch", "sensor"]`, allowing sensor entities to be accidentally assigned as device switches. The selectors now accept only `switch` entities. This affects both the initial setup flow and the options flow.

---

## [0.1.71] - 2026-04-03


### Added

- **Sensor anomaly filter** — each temperature and humidity sensor slot is now individually filtered for implausible spikes before being averaged. If a reading changes by more than the configured **Anomaly Max Temp Delta** (default 3°C/poll) or **Anomaly Max RH Delta** (default 10%/poll) relative to the last accepted value, the spike is rejected and the last known good value is substituted instead. This prevents a single noisy sensor reading from momentarily distorting the average and causing the controller to fire the heater or exhaust unnecessarily.

  If the same sensor stays anomalous for 5 or more consecutive polls (50 seconds) it is treated as a genuine sensor failure rather than a transient spike — the last good value is discarded and the normal sensor unavailability logic takes over. Both thresholds are configurable via number sliders (**Anomaly Max Temp Delta** and **Anomaly Max RH Delta**).

- **Physical disturbance detection** — the controller now detects sudden correlated swings in averaged temperature and/or humidity that are characteristic of a tent door being opened (cold air rushing in, humidity jumping, etc.). When a swing exceeds the configured **Disturbance Temp Delta** (default 2°C/poll) or **Disturbance RH Delta** (default 8%/poll), a disturbance hold is triggered for the configured **Disturbance Hold Time** (default 120 seconds).

  During the hold:
  - All controllable devices (heater, exhaust, humidifier, dehumidifier) are set to **neutral state** (off) — no thrashing or overreaction while conditions are still settling
  - Circulation fan is unaffected — it stays on as normal
  - RLS adaptation is suppressed for the hold duration plus a safety margin to prevent anomalous readings from corrupting the model
  - The `control_mode` sensor shows `disturbance_hold:<reason>` and the `Disturbance Hold Remaining` diagnostic sensor counts down the remaining seconds
  - The `last_action` sensor records the trigger

- **Manual disturbance switch** — a new **Disturbance Active** switch lets you pre-emptively trigger the hold before opening the tent, avoiding the few seconds of controller reaction that would otherwise occur while the auto-detector catches up. Turn it on before opening, turn it off when done (or let it expire automatically after the hold time).

  All three thresholds and the hold time are tunable via number sliders in the integration's device page.

---

## [0.1.70] - 2026-04-03

### Fixed

- **Unused `asyncio` import removed** — `import asyncio` was present at the top of `coordinator.py` but never referenced anywhere in the file. Removed to keep imports clean and avoid any misleading impression that async primitives are being used directly.

- **No-op `.replace()` removed from `_apply_amb`** — the ambient update helper contained `key.replace("mpc_", "mpc_")` which replaces a prefix with itself and does nothing. The entity ID lookup worked correctly despite this, but the dead code was confusing. Simplified to `self._entity_id("number", key)`.

- **Missing debug sensor entities added** — thirteen `debug_*` keys were written to the coordinator data dict every poll cycle but never registered as HA sensor entities, making them invisible in the UI even after enabling debug sensors via Settings → Entities. All thirteen are now registered as hidden diagnostic sensors:
  - `Humidifier Reason` — why the humidifier was turned on or off
  - `Dehumidifier Reason` — why the dehumidifier was turned on or off
  - `Circulation Reason` — why the circulation fan was turned on or off
  - `Debug Target Temp` — effective temperature target being chased this cycle
  - `Debug Target RH` — effective RH target being chased this cycle
  - `Ramped Target Temp` — current ramped temperature target (slides toward actual target at ramp rate)
  - `MPC Horizon` — number of planning steps used by MPC this cycle
  - `MPC Score` — cost of the chosen MPC action plan (lower is better)
  - `MPC Predicted Temp` — temperature predicted at the end of the MPC horizon
  - `MPC Predicted RH` — RH predicted at the end of the MPC horizon
  - `MPC Predicted VPD` — VPD predicted at the end of the MPC horizon
  - `MPC Action Plan` — the first 3 steps of the chosen heater/exhaust action sequence

  All are hidden by default — enable individually via **Settings → Entities**.

---

## [0.1.69] - 2026-04-02

### Changed

- **Flexible sensor configuration — 1 to 3 temperature and humidity sensors** — the integration previously required exactly four sensor slots labelled "Canopy Temperature", "Top Temperature", "Canopy Humidity", and "Top Humidity". This naming was specific to a two-sensor-per-axis setup and made the integration confusing for anyone with a single sensor or a different placement. The four fixed slots have been replaced with **Temperature Sensor 1** (required), **Temperature Sensor 2** (optional), **Temperature Sensor 3** (optional), and the same three slots for humidity. All sensors that are configured are averaged together on every poll cycle — the same `avg()` function that previously averaged the two slots now averages however many you have provided. A single sensor is fully supported with no workarounds needed.

  The MPC model identification button also benefits from this change — it fetches history for all configured sensors, averages their readings at each timestep, and fits the thermal model against the combined average. Previously it required both the "canopy" and "top" sensors to have history; it now only requires at least the first sensor to have data.

  **This is a config schema change (v4 → v5).** Existing installs are migrated automatically on first load — `canopy_temp` becomes `temp_sensor_1`, `top_temp` becomes `temp_sensor_2`, `canopy_rh` becomes `rh_sensor_1`, `top_rh` becomes `rh_sensor_2`, and the third slots are left empty. No user action is required. If you previously had a single physical sensor and pointed both the canopy and top slots at the same entity, after migration you will have Sensor 1 and Sensor 2 pointing at the same entity — you can clear Sensor 2 in **Settings → Devices & Services → Small Grow Tent Controller → Configure** if preferred.

---

## [0.1.68] - 2026-04-02

### Fixed

- **Night Target Humidity stage defaults snapped to 0.5 step grid** — the auto-computed RH defaults for night stages (`STAGE_NIGHT_TARGET_RH`) were derived mathematically to hit exact VPD targets and landed on values like `59.2`, `46.9`, `40.9`, `29.1`, `41.3`. Because the slider step is `0.5`, starting from an off-grid value means every increment lands on `.4`/`.9` instead of `.0`/`.5`. All defaults rounded to the nearest `0.5` boundary: `59.0`, `50.5`, `47.0`, `41.0`, `29.0`, `41.5`. The VPD drift is negligible (< 0.02 kPa) and the slider now behaves identically to the day targets.

---

## [0.1.67] - 2026-04-02

### Fixed

- **`rls_transition_guard` missing from `ControlState` dataclass** — the field was written and read every poll cycle but never declared in the dataclass. Python accepted the dynamic attribute injection at runtime, but the field was not initialised to a safe default on startup, meaning the first read after a fresh HA boot could hit an `AttributeError` on stricter Python/HA versions. Field added with default `0`.

- **Duplicate `async_setup_mpc_results_store` call removed** — `__init__.py` called `async_setup_mpc_results_store()` twice in succession. The second call re-initialised the store object and overwrote the one attached to the coordinator, so persisted R² values loaded by the first call were immediately discarded. The duplicate line has been removed.

- **Exhaust "Day On" safety check was dead code** — the safety override block in `_apply_forced_modes` contained `if self._exhaust_safety_blocks_off(ctx) or True: pass`, making the safety check always evaluate to `True` with a no-op body. The correct behaviour (annotate the debug reason string when safety is active) is now implemented.

- **Duplicate `async_migrate_entry` in `config_flow.py` removed** — both `__init__.py` and `config_flow.py` defined `async_migrate_entry`. HA only calls the one in `__init__.py`, so the version in `config_flow.py` was never executed and was misleading dead code. Removed.

- **`weather_entity` added to v3→v4 config migration** — the v3→v4 migration in `__init__.py` backfilled `ambient_temp` and `ambient_rh` but omitted `weather_entity`, which was also added in v4. Migrated entries from v3 or earlier could hit a missing-key lookup when the coordinator tried to read the weather entity setting. The field is now backfilled to `""` (disabled) during migration.

- **`_reset_stage_targets` no longer uses deprecated internal HA API** — the method previously accessed `hass.data["entity_components"]["number"]`, an undocumented internal that returns `None` silently in several HA versions (causing stage resets to do nothing). Replaced with entity registry lookups + `number.set_value` service calls, the same pattern used everywhere else in the coordinator.

---

## [0.1.66] - 2026-03-31

### Fixed

- **R² sensors and Last Identified timestamp now persist across restarts** — `MpcResultsStore` was fully implemented in `notes.py` (including load, save, and restoring values into `ControlState` on startup) but `async_setup_mpc_results_store` was never called from `__init__.py`. One missing line added. After the next successful identification run the values will be saved to HA's `.storage` directory and survive restarts.

---

## [0.1.66] - 2026-03-31

### Fixed

- **R² sensors and Last Identified timestamp now persist across restarts** — the MPC identification results (R² Temp, R² RH, Last Identified) were stored only in `ControlState` which resets on every HA restart. A new `MpcResultsStore` saves these values to HA's `.storage` directory (same mechanism as the Grow Journal) and restores them into `ControlState` on startup. The R² sensors will now show their last values immediately after restart without needing to re-run identification.

---

## [0.1.65] - 2026-03-31

### Added

- **MPC daytime bias (`a_bias_day`)** — a new number entity **MPC a_bias (Day)** allows a separate self-heating bias for the lights-on window. The existing `a_bias` continues to be used for night MPC; the new `a_bias_day` is used exclusively by day MPC.

  **Why this matters:** the grow light adds significant heat that the model cannot observe directly (it has no light-on input variable). The single `a_bias` value is identified from mixed day/night data and therefore under-estimates daytime self-heating. With `a_bias` too low, MPC thinks the tent needs help reaching temperature targets and fires the heater — but the light heat is already doing that work, causing overshoot.

  Default value: `0.180°C/step` (~1.1°C/min), which accounts for a 100W LED in a 60×60cm tent on top of the passive heating already in `a_passive`. Tune this value up if the heater still fires unnecessarily during the day, or down if the tent consistently runs below target with lights on.

  The `a_bias (Night)` slider is unchanged and continues to be used by night MPC.

---

## [0.1.64] - 2026-03-30

### Fixed

- **`a_passive` floor raised from 0.0 to 0.005** — when `a_passive` collapses to zero the model loses its thermal mass term entirely, causing `a_heater` and `a_exhaust` to absorb all the variance and oscillate wildly. The identified value is ~0.008; a floor of 0.005 prevents the collapse while still allowing meaningful adaptation. This was the root cause of the heater firing above target — with `a_passive=0` and an over-estimated `a_exhaust`, MPC predicted the exhaust would cool the tent dramatically and compensated by turning the heater on simultaneously.

- **`a_exhaust` clamp tightened from -2.0 to -0.5** — the identified value is -0.082; allowing drift to -0.3 or beyond causes MPC to wildly over-estimate exhaust cooling, triggering the heater to compensate.

- **`b_passive` floor raised from 0.001 to 0.003** — same issue as `a_passive` for the humidity model.

---

## [0.1.63] - 2026-03-30

### Fixed

- **RLS humidity model clamps tightened** — `b_exhaust` was allowed to drift to -5.0, but the initial identified value is -1.196 and physical limits suggest -3.0 is a reasonable maximum. When wet towel additions cause sudden RH spikes, RLS over-attributes the change to the exhaust coefficient since the wet towel is an unmodelled input. The tighter clamp (-3.0) prevents the model from becoming so aggressive that MPC runs the exhaust hard to drop RH while simultaneously running the heater to compensate. `b_passive` lower clamp raised from 0.0 to 0.001 (same fix as `a_passive`). `b_bias` clamped to ±2.0 (was ±5.0).

---

## [0.1.62] - 2026-03-30

### Fixed

- **RLS driving `a_heater` negative at light-on events** — when the grow light turns on, the tent temperature rises rapidly due to light heat even with the heater off. RLS saw temperature rising with heater=0 and interpreted this as evidence that the heater has a *negative* effect, driving `a_heater` from +0.17 to -0.08 within minutes of the 16:00 lights-on transition. With a negative `a_heater`, MPC avoids turning the heater on — exactly backwards. Two fixes:

  1. **`a_heater` lower clamp raised from -1.0 to 0.001** — a heater physically cannot cool a tent. The comment already said "must be positive" but the bound was wrong. Same fix applied to `a_passive` (passive heat loss coefficient must also be positive). These are the correct physical constraints.

  2. **RLS transition guard** — RLS is now suppressed for 60 poll cycles (~10 minutes) after every day/night transition. The grow light is a significant unmeasured heat source whose transient warmup at lights-on is the most confusing period for the estimator. Suppressing RLS during this window prevents the light heat spike from corrupting the heater coefficient. The guard is logged at debug level.

### Action required

After installing this update, press **Re-identify MPC Model** to reset all parameters to a clean baseline — the previous RLS run will have left `a_heater` at a negative or near-zero value which will prevent the MPC from heating correctly.

---

## [0.1.61] - 2026-03-30

### Fixed

- **IndentationError on startup after v0.1.60** — the `_get_weather_conditions` method was inserted correctly but the subsequent `_entity_id` method got its `def` line indented at the wrong level (inside the weather method body rather than at class level), causing an `IndentationError` that prevented the integration from loading entirely. Fixed.

---

## [0.1.60] - 2026-03-30

### Added

- **Outdoor weather integration for MPC ambient estimate** — a new optional **Outdoor weather entity** field in the integration Configure screen accepts any HA `weather.*` entity. When set, the controller reads the current outdoor temperature and humidity from the weather entity's attributes each poll cycle and uses them to improve the MPC ambient estimate.

  **Blending logic:** when both a bedroom sensor and a weather entity are configured, the effective ambient is a weighted blend: `α × bedroom + (1-α) × outdoor`, where α is the new **MPC Weather Blend** slider (0.0–1.0, default 0.9). At the default, the bedroom sensor dominates (90%) but outdoor conditions pull the estimate slightly. When the bedroom sensor is unavailable, the controller automatically falls back to outdoor weather only. When neither is configured, the static MPC Ambient Temp/RH sliders are used as before.

  **Why this helps:** outdoor conditions affect bedroom conditions with a lag of minutes to hours. Using outdoor weather as a secondary signal means the ambient estimate never drifts far from reality even if the bedroom sensor drops out, and it provides a meaningful prior for the model in early morning cold snaps or summer heat before the bedroom warms up.

- **`MPC Ambient Source` diagnostic sensor** — shows which source is currently driving the ambient estimate: `bedroom+weather`, `bedroom`, `weather`, or `static_slider`. Hidden by default, enable via Settings → Entities.

- **`MPC Weather Blend` number slider** — controls the blending weight between bedroom sensor and outdoor weather (0.0 = outdoor only, 1.0 = bedroom only, default 0.9).

### Configuration

Go to **Settings → Devices & Services → Small Grow Tent Controller → Configure** and set the new optional **Outdoor weather entity** field to `weather.forecast_home` (or your weather entity). The weather blend slider is in the MPC Parameters fold on the dashboard.

---

## [0.1.59] - 2026-03-29

### Fixed

- **Re-identify MPC Model — journal write now works** — `async_identify_model` called `self._notes_store.async_add_note(note)` but the method is named `async_add`. Fixed.

---

## [0.1.58] - 2026-03-29

### Fixed

- **Re-identify MPC Model button now works** — `async_identify_model` called `self._eid(...)` which doesn't exist as a method on the coordinator. `_eid` is a local closure defined inside `_async_update_data` that wraps `self._entity_id`. The fix adds an equivalent local lambda `_eid = lambda key, domain="number": self._entity_id(domain, key)` at the top of `async_identify_model` so the method can look up number entity IDs correctly.

---

## [0.1.57] - 2026-03-29

### Changed

- **`VERSION` constant in `const.py` corrected** — was stuck at `"0.1.28"` since that constant is used for display in the dashboard controller card and had not been updated during the rapid development cycle from v0.1.29 onward. Now reads `"0.1.57"` and will be kept in sync going forward.
- **Minimum HA version in `hacs.json` bumped to `2024.1.0`** — the integration uses APIs (recorder history, options flow patterns, `async_add_executor_job`) that require at least this version.
- **README updated** to reflect all features added since v0.1.37: RLS adaptation, Re-identify MPC Model button, MPC Auto-Identify Weekly, R² diagnostic sensors, in-HA identification as the primary method with external script as fallback, updated entities list, expanded settings table, and new MPC/RLS troubleshooting entries.

---

## [0.1.56] - 2026-03-29

### Fixed

- **Controller failed to load after v0.1.55** — two `from homeassistant.util import dt as dt_util` imports inside method bodies (`async_identify_model` and the auto-identify weekly block) shadowed the module-level import. Python treats any assignment to a name inside a function — including `import` statements — as a local variable declaration for the entire function scope, so even code *before* the inline import saw `dt_util` as an unbound local. This caused `UnboundLocalError: cannot access local variable 'dt_util'` on the very first call to `_async_update_data`. Both inline imports have been removed — the module-level import at line 13 is the only one needed.

---

## [0.1.55] - 2026-03-29

### Added

- **MPC Model Re-identification button** — a new **Re-identify MPC Model** button in the MPC Parameters section triggers an in-HA model identification run without leaving Home Assistant or running any external scripts. When pressed, the integration reads the last N days of sensor history directly from the HA recorder, runs OLS regression in a background thread, and writes the fitted parameters directly to all nine MPC parameter entities.

- **MPC Identification Days** — a new number slider (1–30 days, default 7) controls how much history the identification uses.

- **MPC Auto-Identify Weekly** — when enabled, the integration automatically re-identifies the model once per week in the background, keeping the model fresh as seasonal conditions change. The weekly clock starts from the last successful identification (manual or automatic).

- **R² diagnostic sensors** — two new hidden diagnostic sensors (`MPC Model R² Temp` and `MPC Model R² RH`) report the fit quality from the last identification run. Values above 0.3 indicate a usable model; above 0.5 is good.

- **`MPC Last Identified`** — a diagnostic sensor showing the timestamp of the last successful identification.

- **Identification results written to Grow Journal** — after every successful identification (manual or automatic), a timestamped entry is added to the Grow Journal with the R² values, sample count, and key fitted parameters.

---

## [0.1.54] - 2026-03-28

### Added

- **RLS (Recursive Least Squares) online model adaptation** — a new **RLS Adaptation** switch in the Grow Tent section enables continuous adaptation of the MPC thermal model from live observations. When enabled, every poll cycle the controller compares what the model predicted would happen (given the previous device states) against what actually happened, and adjusts the model parameters to reduce that error.

  **How it works:** RLS maintains a parameter vector and covariance matrix for both the temperature model (a_heater, a_exhaust, a_passive, a_bias) and the humidity model (b_exhaust, b_passive, b_bias). After each observation, it applies a weighted update that gives more weight to recent data and discounts older data at a rate controlled by the forgetting factor λ.

  **Forgetting factor (λ):** configurable from 0.990 to 1.000, default 0.999. At λ=0.999 the effective memory is ~1000 poll cycles (~2.8 hours), meaning the model adapts to seasonal changes over days rather than minutes. At λ=0.990 the memory is ~100 cycles (~17 minutes) — faster adaptation but more sensitive to noise.

  **Safety:** parameter estimates are sanity-clamped to physically plausible ranges so the model cannot drift to absurd values. Updated parameters are written back to the MPC number entities every cycle so they are visible on the dashboard, persist across restarts, and can be monitored over time.

  **Usage:** RLS is off by default. Enable it once you are satisfied with basic MPC performance and want the model to adapt automatically to seasonal changes, equipment changes, or grow-stage transitions.

---

## [0.1.53] - 2026-03-28

### Fixed

- **MPC Ambient Temp and RH now update on the dashboard** — the coordinator was reading the lung room sensor and using the live value for MPC calculations, but never writing it back to the `MPC Ambient Temp` and `MPC Ambient RH` number entities. The sliders therefore stayed frozen at whatever value the user had last set manually, making it appear as if the sensor integration was not working. The coordinator now calls `number.set_value` to sync the number entities whenever the live sensor reading differs by more than 0.05°C / 0.5% RH, so the dashboard always reflects the actual ambient conditions being used by the MPC. You can now disable the separate `Update MPC Ambient Conditions` automation — the integration handles this automatically.

---

## [0.1.52] - 2026-03-28

### Fixed

- **Exhaust no longer cycles in Night MPC and Night VPD Chase modes** — both `_apply_night_mpc` and `_apply_night_vpd_chase` applied the stage exhaust night profile on top of the MPC/VPD-chase exhaust decision. When the profile was `auto`, it checked whether conditions exceeded the max limits and turned the exhaust off if not — immediately undoing the decision the MPC or VPD chase had just made. This caused the exhaust to cycle every ~10 seconds as the controller turned it on (MPC decision) then off (profile override) then on again. The `auto` override is now removed from both methods — the MPC and VPD chase own the exhaust decision in these modes. The `on` profile (force exhaust on continuously) is still applied as before since that overrides in only one direction.

- **Options flow save handler now preserves all optional fields** — `vol.Optional` fields with `suggested_value` are absent from `user_input` when the user doesn't explicitly interact with them. The save handler now explicitly merges all optional fields (ambient sensors and device switch assignments) from the existing config when absent from `user_input`, preventing any field from being silently dropped when saving.

---

## [0.1.51] - 2026-03-27

### Changed

- **Options flow is now a single screen** — the Configure screen previously had two steps (device toggles, then entity selectors), which meant users had to click through step 1 before seeing the entity fields including the new ambient sensor fields. This caused persistent confusion since HA often shows step 1 as a standalone form with no obvious indication that a second screen follows. The options flow is now a single step (`init`) showing all settings — device enable toggles, sensor assignments, optional lung room sensors, and device switch entities — on one screen.

### Fixed

- **Ambient sensor fields now definitively visible** — the two-step flow architecture was the root cause. With a single step there is no hidden second screen to miss.

---

## [0.1.50] - 2026-03-27

### Fixed

- **Options flow 500 error on Configure** — v0.1.49 attempted to store `config_entry` in `OptionsFlowHandler.__init__` via `self.config_entry = config_entry`, but `config_entries.OptionsFlow` already defines `config_entry` as a read-only property in recent HA versions, causing an `AttributeError` and a 500 error when clicking the cog wheel. The fix is to revert to a no-argument `__init__` and rely on the base class to provide `self.config_entry` automatically, which is how HA intends it to work. The existing uses of `self.config_entry.data` and `self.config_entry.options` throughout the flow continue to work correctly via the base class property.

---

## [0.1.49] - 2026-03-27

### Fixed

- **Options flow now receives `config_entry` explicitly** — in recent HA versions `OptionsFlow` no longer automatically injects `self.config_entry`. The `OptionsFlowHandler` was constructed with no arguments and relied on HA injecting the config entry, which silently failed — causing the Configure screen to open with empty defaults and potentially no fields rendered at all. The handler now receives `config_entry` explicitly from `async_get_options_flow` and stores it in `__init__`. This is the root cause of the ambient sensor fields not appearing.

- **Ambient entity ID empty string handled safely** — `_get_option(CONF_AMBIENT_TEMP)` returns `""` when the field is not configured. The coordinator now uses `or None` to convert empty strings to `None` before checking, preventing any possibility of passing an empty string to `_get_state_float`.

---

## [0.1.48] - 2026-03-27

### Fixed

- **Ambient sensor fields now visible in Configure screen** — the fields were present in the options flow code but not rendering correctly for two reasons: (1) `vol.Optional` fields with an empty string default are suppressed by some HA versions when no value is set; they now use `description={"suggested_value": ...}` which forces the field to always render. (2) When saving, `vol.Optional` fields left blank are absent from `user_input`, so previously saved values were being lost on every Configure save. The save handler now explicitly preserves ambient field values whether or not the user touched them.

---

## [0.1.47] - 2026-03-27

### Fixed

- **Config migration v3→v4 now actually fires** — v0.1.46 added `async_migrate_entry` to `config_flow.py` but HA calls the one in `__init__.py`, which already handled v1→v2 and v2→v3 but returned `True` early for v3 without upgrading to v4. The v3→v4 migration is now correctly placed in `__init__.py`. Existing installations will upgrade automatically on restart and the ambient sensor fields will be accessible in **Settings → Devices & Services → Small Grow Tent Controller → Configure**.

- **Targets no longer reset on restart (properly this time)** — v0.1.46's `is_first_stage_poll` fix only suppressed the reset for a single poll, but the real issue is that `async_config_entry_first_refresh()` runs before number entities are set up and their saved values are restored by `RestoreEntity`. The single-poll delay was not long enough. The fix is now a 6-poll startup window (~60 seconds) during which stage changes are recorded but never acted on. Genuine stage changes (which require manual user action) are unaffected.

---

## [0.1.46] - 2026-03-26

### Fixed

- **Ambient sensor config fields now accessible on existing installations** — v0.1.45 bumped the config flow version to 4 but did not include a migration function, so existing entries could not access the reconfigure screen. An `async_migrate_entry` function is now included that upgrades v3 entries to v4 by adding the two new optional ambient sensor fields with empty defaults. No user action is required — existing installations upgrade automatically on restart.

- **Targets no longer reset to stage defaults on every HA restart** — the stage-change detection logic compares `current_stage` to `last_stage` (which starts as `""` in `ControlState`). On the first poll after startup, `RestoreEntity` had not yet restored the stage select entity's saved state, so the coordinator always saw a stage change and reset all targets. A new `is_first_stage_poll` flag suppresses the reset on the very first poll cycle, giving `RestoreEntity` time to restore saved values. Subsequent genuine stage changes still reset targets normally.

- **Controller card icon and colour now correct in MPC modes** — `control_mode == 'mpc'` and `control_mode == 'night_mpc'` now show `mdi:cpu-64-bit` in green, matching the visual language of other active control modes.

---

## [0.1.45] - 2026-03-26

### Added

- **Ambient sensor integration** — the integration configuration now includes two optional entity fields: **Lung room temperature sensor** and **Lung room humidity sensor**. When set, the MPC controller reads these sensors every poll cycle and uses their current values as the ambient temperature and RH estimates, replacing the static `MPC Ambient Temp` and `MPC Ambient RH` number sliders. The sliders remain as fallback values when sensors are unavailable or not configured.

  This replaces the need for a separate HA automation to keep the ambient values in sync. To configure, go to **Settings → Devices & Services → Small Grow Tent Controller → Configure** and select your lung room sensors in the new optional fields.

  The `MPC Ambient Temp` and `MPC Ambient RH` number entities remain visible as diagnostic indicators — when sensors are configured they reflect the live sensor readings used by the model.

### ⚠️ Config Entry Migration

The config flow version has been bumped from 3 to 4. Existing installations will continue to work without reconfiguration — the new fields are optional and default to empty (disabled). To add your lung room sensors, go to **Settings → Devices & Services → Small Grow Tent Controller → Configure**.

---

## [0.1.44] - 2026-03-26

### Added

- **Night Mode: MPC** — a new `MPC` option in the Night Mode selector runs Model Predictive Control during the light-off window using the night targets (Night VPD Target, Night Target Temperature, Night Target Humidity). Behaviour mirrors the day MPC mode with two night-specific additions always enforced on top:
  - **Dew-point floor** — if MPC leaves the heater off but temperature is at or below dew point + margin, the heater turns on regardless to prevent condensation.
  - **Stage exhaust night profile** — the per-stage exhaust setting (on/auto) is applied on top of the MPC exhaust decision, consistent with all other night modes.
  - Humidity devices fall back to simple RH deadband control (same as day MPC).
  - All MPC parameters (model coefficients, weights, horizon) are shared with day MPC.
  - Hard limits still fire before MPC, same as all other modes.

---

## [0.1.43] - 2026-03-26

### Fixed

- **MPC NameError on sensor dropout** — a stale `_mpc_simulate(temp0, rh0, ...)` call was left in `_apply_mpc_day` after the v0.1.42 refactor. The variables `temp0` and `rh0` were defined in the old method body but removed when the optimisation was moved to the thread executor. This caused a `NameError` crash whenever MPC ran with unavailable sensors. The three stale lines have been removed — `temp_pred`, `rh_pred`, and `vpd_pred` are now used directly from the executor return value as intended.

---

## [0.1.42] - 2026-03-26

### Fixed

- **MPC no longer freezes Home Assistant** — the combinatorial optimisation in v0.1.41 ran synchronously on the HA event loop. With the default horizon of 18 steps that meant evaluating 4^18 ≈ 68 billion combinations every 10 seconds, blocking HA entirely.

  Two changes fix this:
  - The optimisation now runs in a **thread-pool executor** (`async_add_executor_job`) so it never touches the event loop regardless of horizon length.
  - The **horizon is hard-capped at 6 steps** (4^6 = 4,096 combinations, completes in <1ms). The number entity range is now 1–6 with a default of 3. A horizon of 3–6 steps (30–60 seconds) is more than sufficient for a tent with a ~21-minute thermal time constant.

---

## [0.1.41] - 2026-03-26

### Added

- **MPC (Model Predictive Control) day mode** — a new `Day Mode` selector in the Grow Tent section lets you choose how the controller manages conditions during the light-on window:

  - **VPD Chase** *(default — existing behaviour unchanged)*
  - **MPC** — uses a first-order thermal/humidity model identified from your real sensor history to plan heater and exhaust actions several steps ahead, reducing overshoot and handling actuator lag explicitly
  - **Limits Only** — only hard temperature and humidity limits are enforced (previously controlled by the VPD Chase switch)

  The MPC controller evaluates all combinations of heater/exhaust states over a configurable planning horizon (default 18 steps = 3 minutes), simulates tent conditions forward using the identified model, and selects the sequence that minimises a weighted cost of VPD error, temperature error, RH error, and unnecessary device switching. Only the first step of the optimal plan is executed each cycle.

  Humidity devices (humidifier/dehumidifier) fall back to simple RH deadband control in MPC mode — a reliable humidity model requires a proper humidifier sensor, which will be added in a future release.

- **MPC model parameters** — 15 new number entities in a collapsible MPC Parameters section in Tuning/Safety, pre-populated with the parameters identified from the included `mpc_identify.py` script. Key parameters: ambient temp/RH, model coefficients (a_heater, a_exhaust, a_passive, a_bias, b_exhaust, b_passive, b_bias), cost weights (VPD, temp, RH, switch penalty), and horizon steps.

- **`mpc_identify.py`** — standalone Python script (not part of the HA integration) that reads 7 days of raw state history from your HA SQLite database, fits the thermal and humidity model parameters using ordinary least squares regression, validates the fit with plots, and outputs the parameters ready to paste into the controller. Run once after installation to identify your tent's model. See the script header for usage instructions.

### Notes

- The VPD Chase switch remains for backward compatibility. When Day Mode is set to MPC or Limits Only, the VPD Chase switch has no effect.
- MPC operates only during the day (light-on) window. Night mode (Dew Protection / VPD Chase / VPD Chase No Heater) is unchanged.
- Hard limits still fire before MPC, same as with VPD Chase.
- Default model parameters are pre-set to values identified from a real 60×60cm grow tent with a ceramic fan heater and exhaust fan. Run `mpc_identify.py` on your own history for best results.

---

## [0.1.40] - 2026-03-25

### Fixed

- **Exhaust Mode Day On / Night On now fall back to Auto outside their window** — previously, selecting `Day On` would force the exhaust off at night, and `Night On` would force it off during the day. This is now corrected: when outside their active window, both modes hand control back to the normal auto logic (VPD chase, hard limits, night mode) exactly as if the mode were set to `Auto`. The exhaust is only forced on during the active window — outside it, the controller decides.

  When the controller is disabled, `Day On` and `Night On` are treated as `Auto` (no auto logic runs when disabled, so the exhaust is left in whatever state it's in).

---

## [0.1.39] - 2026-03-25

### Fixed

- **Night Target Temperature now displays one decimal place** — the entity now sets `suggested_display_precision = 1` so HA renders it as e.g. `21.0°C` consistently, matching the day Target Temperature display. The same attribute is set on the day Target Temperature and Night Target Humidity entities for explicit consistency across all target number cards.

---

## [0.1.38] - 2026-03-24

### Added

- **Night Targets** — separate VPD, temperature, and humidity targets for the night (light-off) window. These are independent from the day targets and auto-reset on stage change alongside them:

  | Stage | Night Temp | Night VPD | Night RH |
  |---|---|---|---|
  | Seedling | 19°C | 0.70 kPa | 59.2% |
  | Early Vegetative | 20°C | 0.95 kPa | 50.5% |
  | Late Vegetative | 21°C | 1.10 kPa | 46.9% |
  | Early Bloom | 21°C | 1.25 kPa | 40.9% |
  | Late Bloom | 20°C | 1.45 kPa | 29.1% |
  | Drying | 16°C | 0.90 kPa | 41.3% |

  Night temp defaults to day temp − 5°C. Night RH is auto-calculated to be congruent with night temp + night VPD target. All three values are freely adjustable. Night targets are used by VPD Chase and VPD Chase (No Heater) night modes. Dew Protection night mode is unaffected — it uses dew point + margin as always.

- **Temperature Ramp Rate** — a new Tuning/Safety slider (°C/min, default 1.0, range 0–5, 0 = disabled) that limits how fast the controller's effective temperature target can change. This prevents abrupt jumps at day↔night transitions and acts as a global protection against rapid temperature changes at any time. The ramp applies in both directions and slides the effective target toward the actual target at no more than the configured rate per poll cycle. The heater safety trip runs independently and is unaffected by the ramp.

- **Exhaust Mode: Day On and Night On** — two new options in the Exhaust Fan mode dropdown:
  - **Day On** — exhaust on during the light-on window, off at night
  - **Night On** — exhaust on during the light-off window, off during the day
  - Exhaust Safety always overrides both modes — the exhaust cannot be turned off while safety thresholds are exceeded, regardless of the mode setting.

### Changed

- The Targets section of the dashboard is now split into **☀️ Day Targets** and **🌙 Night Targets**, each with their own VPD, temperature, and RH sliders displayed in a 3-column grid.
- Tuning/Safety section now includes the **Temp Ramp Rate** slider.

---

## [0.1.37] - 2026-03-23

### Fixed

- **Hard limits now enforced before Night VPD Chase** — previously, when Night Mode was set to VPD Chase or VPD Chase (No Heater), the hard temperature and humidity limits were never checked at night. If RH exceeded the max limit, the controller would ignore it and continue trying to chase the VPD target — which in the case of low VPD + high RH could mean turning the heater on and exhaust off, making the RH problem worse.

  Hard limits now run before night VPD chase with the same priority they have during the day. If a limit is breached, the hard limit response fires and VPD chase is skipped for that cycle.

---

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
