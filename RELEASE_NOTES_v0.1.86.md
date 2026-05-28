# Small Grow Tent Controller — v0.1.86

## Drying Stage: Single Set of Objectives

Before this release the Drying stage carried two independent sets of targets:
a day set (21 °C / 55 % RH / 0.90 kPa) and a night set (16 °C / 52.3 % RH /
0.70 kPa). Because the light is always off during drying there is no actual
day/night boundary, so this split served no purpose — it could only cause the
environment to quietly drift between two different operating points over the
course of 24 hours.

From v0.1.86 the controller treats Drying as a single-objective stage. The same
temperature, humidity, and VPD targets apply around the clock.

---

### What changed

#### `const.py`
The Drying entries in the three night-target dictionaries have been updated to
mirror the day defaults:

| Parameter | Before (night) | After (night = day) |
|---|---|---|
| Temperature | 16 °C | **21 °C** |
| Relative Humidity | 52.3 % | **55 %** |
| VPD | 0.70 kPa | **0.90 kPa** |

#### `coordinator.py` — stage reset
`_reset_stage_targets` now branches on the incoming stage. For all stages
except Drying, the existing lookup from `STAGE_NIGHT_TARGET_*` is unchanged.
For Drying, the night slots are written with the same values as the day slots,
so the night target sliders in the UI are immediately aligned with the day
targets the moment you switch to Drying.

#### `coordinator.py` — runtime context
In `_apply_control`, when building the `_Ctx` for the control cycle, the three
night target context fields (`night_vpd_target`, `night_target_temp`,
`night_target_rh`) are now populated from the day target data keys whenever
`drying=True`. This is a belt-and-suspenders guard: even if the night sliders
were edited manually after switching to Drying, the coordinator will always use
the day targets and the manual edits will have no effect.

#### `README.md`
- The night targets table now shows the Drying row as `0.90 kPa *(= day)*` /
  `21 °C *(= day)*` / `55 % *(= day)*`.
- Section **3. Drying mode** rewritten to document the single-objective
  behaviour and explain both enforcement layers.

---

### Upgrade notes

This is a non-breaking change. No config entries, entity IDs, or stored states
are modified. The integration version in `manifest.json` and `const.py`
increments from **0.1.85 → 0.1.86**.

If you are currently on the Drying stage, the night target sliders will be
reconciled to the day values the next time you manually select the Drying stage
(or any stage change is triggered). In the meantime, the runtime override in
the coordinator ensures the correct single-objective targets are used
immediately — no action is required on your part.
