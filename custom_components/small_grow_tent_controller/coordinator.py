from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .climate_math import safe_float, avg, dew_point_c, vpd_leaf_kpa
from .const import (
    DOMAIN,
    DEFAULT_STAGE,
    STAGE_TARGET_VPD_KPA,
    CONF_LIGHT_SWITCH,
    CONF_CIRC_SWITCH,
    CONF_EXHAUST_SWITCH,
    CONF_HEATER_SWITCH,
    CONF_HUMIDIFIER_SWITCH,
    CONF_DEHUMIDIFIER_SWITCH,
    CONF_USE_LIGHT,
    CONF_USE_CIRCULATION,
    CONF_USE_EXHAUST,
    CONF_USE_HEATER,
    CONF_USE_HUMIDIFIER,
    CONF_USE_DEHUMIDIFIER,
    CONF_CANOPY_TEMP,
    CONF_TOP_TEMP,
    CONF_CANOPY_RH,
    CONF_TOP_RH,
    CONF_EXHAUST_SAFETY_OVERRIDE,
    CONF_EXHAUST_SAFETY_MAX_TEMP_C,
    CONF_EXHAUST_SAFETY_MAX_RH,
)

_LOGGER = logging.getLogger(__name__)

# Notification ID suffix (prefixed per entry to avoid cross-instance collisions)
_NOTIF_SENSORS_UNAVAILABLE = "sensors_unavailable"

# Stage-specific night behaviour: exhaust_mode = "on" | "auto"
STAGE_NIGHT_PROFILE: dict[str, dict[str, Any]] = {
    "Seedling":     {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Vegetative":   {"exhaust_mode": "on",   "dew_margin_add_c": 0.0},
    "Early Flower": {"exhaust_mode": "on",   "dew_margin_add_c": 0.0},
    "Mid Flower":   {"exhaust_mode": "on",   "dew_margin_add_c": 0.0},
    "Late Flower":  {"exhaust_mode": "on",   "dew_margin_add_c": 0.0},
    "Drying":       {"exhaust_mode": "on",   "dew_margin_add_c": 1.0},
}

# Light schedule defaults — must match time.py defaults exactly
_DEFAULT_LIGHT_ON  = time(9,  0, 0)
_DEFAULT_LIGHT_OFF = time(21, 0, 0)


@dataclass
class ControlState:
    last_heater_change:       datetime | None = None
    last_exhaust_change:      datetime | None = None
    last_light_change:        datetime | None = None
    last_humidifier_change:   datetime | None = None
    last_dehumidifier_change: datetime | None = None

    # Heater pulse control
    heater_pulse_until:    datetime | None = None
    heater_cooldown_until: datetime | None = None

    # Heater safety: max continuous run time
    heater_on_since:          datetime | None = None
    heater_max_lockout_until: datetime | None = None

    # Sensor availability tracking
    sensors_were_unavailable: bool = False

    # Stage change detection (for VPD target auto-reset)
    last_stage: str = ""

    # Last action recorded by the controller
    last_action: str = "none"


# ---------------------------------------------------------------------------
# Runtime context — passed between the focused sub-methods each cycle
# ---------------------------------------------------------------------------
@dataclass
class _Ctx:
    data:               dict[str, Any]
    now:                datetime
    stage:              str
    drying:             bool
    is_day:             bool
    avg_temp:           float
    avg_rh:             float
    dew:                float
    vpd:                float
    min_temp:           float
    max_temp:           float
    min_rh:             float
    max_rh:             float
    dew_margin:         float
    heater_hold:        float
    exhaust_hold:       float
    humidifier_hold:    float
    dehumidifier_hold:  float
    exhaust_eid:        str | None
    heater_eid:         str | None
    humidifier_eid:     str | None
    dehumidifier_eid:   str | None
    heater_on:          bool
    exhaust_on:         bool
    humidifier_on:      bool
    dehumidifier_on:    bool
    exhaust_safety_on:  bool
    exhaust_safety_max_temp: float
    exhaust_safety_max_rh:   float
    heater_max_run_s:   float


class GrowTentCoordinator(DataUpdateCoordinator[dict[str, Any]]):

    def __init__(self, hass: HomeAssistant, entry):
        self.hass  = hass
        self.entry = entry
        self.control = ControlState()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=10),
        )

    # ------------------------------------------------------------------ #
    #  Generic helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_state_float(self, entity_id: str) -> float | None:
        st = self.hass.states.get(entity_id)
        return None if st is None else safe_float(st.state)

    def _get_option(self, key: str) -> Any:
        # options take priority; both False and "" are legitimate values
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key)

    def _use(self, conf_key: str) -> bool:
        v = self._get_option(conf_key)
        return bool(v) if v is not None else True

    def _get_mode(self, mode_key: str) -> str:
        eid = self._entity_id("select", mode_key)
        st  = self.hass.states.get(eid)
        if st is None:
            return "Auto"
        return st.state if st.state in ("Auto", "On", "Off") else "Auto"

    def _now(self) -> datetime:
        return dt_util.now()

    def _is_time_between(self, now_t: time, start: time, end: time) -> bool:
        if start <= end:
            return start <= now_t < end
        return now_t >= start or now_t < end

    def _entity_id(self, domain: str, key: str) -> str:
        registry  = er.async_get(self.hass)
        unique_id = f"{self.entry.entry_id}_{key}"
        eid = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        return eid or f"{domain}.{self.entry.entry_id}_{key}"

    def _switch_is_on(self, entity_id: str | None) -> bool | None:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        return None if st is None else st.state == "on"

    def _can_toggle(self, last_change: datetime | None, hold_seconds: float) -> bool:
        return last_change is None or (self._now() - last_change).total_seconds() >= hold_seconds

    def _get_entity_state(self, entity_id: str) -> str | None:
        st = self.hass.states.get(entity_id)
        return None if st is None else st.state

    def _num(self, entity_id: str, default: float) -> float:
        val = safe_float(self._get_entity_state(entity_id))
        return default if val is None else val

    def _parse_time(self, s: str | None, default: time) -> time:
        if not s:
            return default
        try:
            parts = s.split(":")
            return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
        except Exception:
            return default

    async def _async_switch(self, entity_id: str, turn_on: bool, blocking: bool = False) -> None:
        """Switch a device. blocking=True reserved for safety-critical trips."""
        await self.hass.services.async_call(
            "switch",
            "turn_on" if turn_on else "turn_off",
            {"entity_id": entity_id},
            blocking=blocking,
        )

    def _record_action(self, description: str) -> None:
        """Store the last action with a timestamp for the last_action sensor."""
        ts = dt_util.as_local(self._now()).strftime("%H:%M:%S")
        self.control.last_action = f"{description} @ {ts}"

    # ------------------------------------------------------------------ #
    #  Heater helpers                                                      #
    # ------------------------------------------------------------------ #

    def _heater_pulse_plan(self, error_c: float) -> tuple[int, int]:
        """Proportional on/off pulse plan: (on_seconds, off_seconds)."""
        if error_c >= 1.5: return (9999, 0)
        if error_c >= 0.8: return (30, 30)
        if error_c >= 0.3: return (10, 50)
        return (0, 60)

    def _heater_allowed_on(self, now: datetime) -> bool:
        return not (self.control.heater_max_lockout_until and now < self.control.heater_max_lockout_until)

    # ------------------------------------------------------------------ #
    #  Exhaust safety                                                      #
    # ------------------------------------------------------------------ #

    def _exhaust_safety_blocks_off(self, ctx: _Ctx) -> bool:
        return ctx.exhaust_safety_on and (
            ctx.avg_temp >= ctx.exhaust_safety_max_temp or
            ctx.avg_rh   >= ctx.exhaust_safety_max_rh
        )

    # ------------------------------------------------------------------ #
    #  Sensor availability                                                 #
    # ------------------------------------------------------------------ #

    def _handle_sensor_availability(self, sensors_ok: bool) -> None:
        notif_id = f"{DOMAIN}_{self.entry.entry_id}_{_NOTIF_SENSORS_UNAVAILABLE}"

        if not sensors_ok:
            if not self.control.sensors_were_unavailable:
                self.control.sensors_were_unavailable = True
                persistent_notification.async_create(
                    self.hass,
                    message=(
                        f"**{self.entry.title}** — one or more environment sensors "
                        f"are unavailable or returning invalid readings.\n\n"
                        f"Automatic control has been paused until all sensors "
                        f"report valid values.\n\n"
                        f"Check: **Settings → Devices & Services → {self.entry.title} → Configure** "
                        f"to verify the assigned sensor entities."
                    ),
                    title="Grow Tent: Sensors Unavailable",
                    notification_id=notif_id,
                )
                _LOGGER.warning(
                    "%s: one or more sensors unavailable — controller paused",
                    self.entry.title,
                )
        else:
            if self.control.sensors_were_unavailable:
                self.control.sensors_were_unavailable = False
                persistent_notification.async_dismiss(self.hass, notif_id)
                _LOGGER.info(
                    "%s: all sensors restored — controller resuming",
                    self.entry.title,
                )

    # ------------------------------------------------------------------ #
    #  Manual override application                                         #
    # ------------------------------------------------------------------ #

    async def _apply_forced_modes(self, ctx: _Ctx) -> _Ctx:
        """Apply On/Off manual overrides; clears the eid to skip auto-control."""
        now = ctx.now

        for eid_attr, mode_key, label, hold_attr, on_attr in [
            ("heater_eid",       "heater_mode",       "Heater",       "heater_hold",       "heater_on"),
            ("humidifier_eid",   "humidifier_mode",   "Humidifier",   "humidifier_hold",   "humidifier_on"),
            ("dehumidifier_eid", "dehumidifier_mode", "Dehumidifier", "dehumidifier_hold", "dehumidifier_on"),
        ]:
            eid  = getattr(ctx, eid_attr)
            mode = self._get_mode(mode_key) if eid else "Auto"
            if mode == "Auto" or not eid:
                continue
            desired = mode == "On"
            cur = self._switch_is_on(eid)
            if cur is not None and cur != desired:
                await self._async_switch(eid, desired)
                setattr(self.control, f"last_{label.lower()}_change", now)
                self._record_action(f"{label} {'ON' if desired else 'OFF'} · override:{mode.lower()}")
            setattr(ctx, on_attr, desired)
            setattr(ctx, eid_attr, None)

        # Exhaust: special safety check
        eid  = ctx.exhaust_eid
        mode = self._get_mode("exhaust_mode") if eid else "Auto"
        if mode != "Auto" and eid:
            desired = mode == "On"
            reason  = f"override:{mode.lower()}"
            if mode == "Off" and self._exhaust_safety_blocks_off(ctx):
                desired = True
                reason  = "override:off_blocked_by_safety"
            ctx.data["debug_exhaust_reason"] = reason
            cur = self._switch_is_on(eid)
            if cur is not None and cur != desired:
                await self._async_switch(eid, desired)
                self.control.last_exhaust_change = now
                self._record_action(f"Exhaust {'ON' if desired else 'OFF'} · {reason}")
            ctx.exhaust_on  = desired
            ctx.exhaust_eid = None

        return ctx

    # ------------------------------------------------------------------ #
    #  Heater safety trip                                                  #
    # ------------------------------------------------------------------ #

    async def _apply_heater_safety(self, ctx: _Ctx) -> bool:
        """Returns True if a safety trip fired and the caller should return early."""
        now = ctx.now
        ctx.data["debug_heater_max_run_s"] = ctx.heater_max_run_s
        ctx.data["debug_heater_lockout"] = (
            "active"
            if (self.control.heater_max_lockout_until and now < self.control.heater_max_lockout_until)
            else "inactive"
        )

        # Enforce active lockout
        if self.control.heater_max_lockout_until and now < self.control.heater_max_lockout_until:
            if ctx.heater_on and ctx.heater_eid:
                await self._async_switch(ctx.heater_eid, False, blocking=True)
                self.control.last_heater_change = now
                self.control.heater_on_since = None
                self._record_action("Heater OFF · safety lockout active")
                ctx.heater_on = False

        # Trip: max run exceeded
        if (
            ctx.heater_max_run_s > 0
            and ctx.heater_on
            and ctx.heater_eid
            and self.control.heater_on_since is not None
            and (now - self.control.heater_on_since).total_seconds() >= ctx.heater_max_run_s
        ):
            await self._async_switch(ctx.heater_eid, False, blocking=True)
            self.control.last_heater_change = now
            self.control.heater_on_since = None
            self.control.heater_max_lockout_until = now + timedelta(seconds=ctx.heater_hold)
            self._record_action("Heater OFF · SAFETY TRIP max run time exceeded")

            ctx.data["control_mode"]         = "safety_trip:heater_max_run"
            ctx.data["debug_heater_reason"]  = "max_run_time_exceeded -> forced_off"
            ctx.data["debug_heater_lockout"] = "active"
            return True

        return False

    # ------------------------------------------------------------------ #
    #  Drying mode                                                         #
    # ------------------------------------------------------------------ #

    async def _apply_drying_mode(self, ctx: _Ctx) -> None:
        limit = self._eval_hard_limits(ctx)
        ctx.data["control_mode"] = "drying_hard_limits_only" if limit is None else f"drying_hard_limit:{limit}"

        if limit is None:
            await self._heater_off(ctx, "drying: in-band -> neutral")
            await self._exhaust_off_if_on(ctx, "drying: in-band -> neutral")
        elif limit == "temp_below_min":
            await self._heater_on_if_allowed(ctx, "drying: temp_below_min -> heater_on")
            await self._exhaust_off_if_on(ctx, "drying: temp_below_min -> exhaust_off")
        elif limit == "temp_above_max":
            await self._heater_off(ctx, "drying: temp_above_max -> heater_off")
            await self._exhaust_on_if_off(ctx, "drying: temp_above_max -> exhaust_on")
        elif limit == "rh_above_max":
            if ctx.avg_temp > ctx.min_temp:
                await self._exhaust_on_if_off(ctx, "drying: rh_above_max -> exhaust_on")
            if ctx.avg_temp >= ctx.min_temp:
                await self._heater_off(ctx, "drying: rh_above_max -> heater_off")
            await self._humidifier_off(ctx)
            await self._dehumidifier_on(ctx)
        elif limit == "rh_below_min":
            await self._exhaust_off_if_on(ctx, "drying: rh_below_min -> exhaust_off")
            if ctx.avg_temp > ctx.min_temp:
                await self._heater_off(ctx, "drying: rh_below_min -> heater_off")
            await self._dehumidifier_off(ctx)
            await self._humidifier_on(ctx)

    # ------------------------------------------------------------------ #
    #  Night mode                                                          #
    # ------------------------------------------------------------------ #

    async def _apply_night_mode(self, ctx: _Ctx) -> None:
        profile      = STAGE_NIGHT_PROFILE.get(ctx.stage, {"exhaust_mode": "on", "dew_margin_add_c": 0.0})
        exhaust_mode = profile.get("exhaust_mode", "on")
        dew_margin_night = ctx.dew_margin + float(profile.get("dew_margin_add_c", 0.0))

        ctx.data["control_mode"] = f"night_{exhaust_mode}_dewpoint_protect"

        # Humidifier always off at night; dehumidifier if RH too high
        await self._humidifier_off(ctx, reason="night: force_off")
        if ctx.avg_rh > ctx.max_rh:
            await self._dehumidifier_on(ctx)
            ctx.data["debug_dehumidifier_reason"] = "night: rh_above_max -> on"
        elif ctx.dehumidifier_on:
            await self._dehumidifier_off(ctx)
            ctx.data["debug_dehumidifier_reason"] = "night: rh_ok -> off"

        # Heater pulse plan
        target_temp = min(ctx.dew + dew_margin_night, ctx.max_temp)
        error       = target_temp - ctx.avg_temp
        on_s, off_s = self._heater_pulse_plan(error)

        ctx.data["debug_heater_target_c"] = round(target_temp, 2)
        ctx.data["debug_heater_error_c"]  = round(error, 2)

        await self._apply_heater_pulse(ctx, on_s, off_s)

        # Exhaust night profile
        if exhaust_mode == "on":
            ctx.data["debug_exhaust_reason"] = "night: profile=on"
            await self._exhaust_on_if_off(ctx, "night: profile=on")
        elif exhaust_mode == "auto":
            want = ctx.avg_rh > ctx.max_rh or ctx.avg_temp > ctx.max_temp
            ctx.data["debug_exhaust_reason"] = f"night: auto want_exhaust={want}"
            if want:
                await self._exhaust_on_if_off(ctx, "night: auto on")
            else:
                await self._exhaust_off_if_on(ctx, "night: auto off")

    async def _apply_heater_pulse(self, ctx: _Ctx, on_s: int, off_s: int) -> None:
        now = ctx.now
        if on_s == 0:
            ctx.data["debug_heater_reason"] = "night: at/above dew target -> off"
            self.control.heater_pulse_until    = None
            self.control.heater_cooldown_until = None
            await self._heater_off(ctx, "night: at/above dew target")
            return

        if self.control.heater_cooldown_until and now < self.control.heater_cooldown_until:
            ctx.data["debug_heater_reason"] = "night: cooldown"
            await self._heater_off(ctx, "night: cooldown")
            return

        ctx.data["debug_heater_reason"] = f"night: pulse plan on={on_s}s off={off_s}s"

        if not ctx.heater_on:
            self.control.heater_pulse_until = now + timedelta(seconds=on_s)
            if ctx.heater_eid and self._heater_allowed_on(now) and self._can_toggle(self.control.last_heater_change, ctx.heater_hold):
                await self._async_switch(ctx.heater_eid, True)
                self.control.last_heater_change = now
                self._record_action(f"Heater ON · night pulse on={on_s}s off={off_s}s")
                ctx.heater_on = True
        else:
            if self.control.heater_pulse_until is None:
                self.control.heater_pulse_until = now + timedelta(seconds=on_s)

        if (
            ctx.heater_on
            and self.control.heater_pulse_until
            and now >= self.control.heater_pulse_until
            and ctx.heater_eid
            and self._can_toggle(self.control.last_heater_change, ctx.heater_hold)
        ):
            await self._async_switch(ctx.heater_eid, False)
            self.control.last_heater_change    = now
            self.control.heater_pulse_until    = None
            self.control.heater_cooldown_until = now + timedelta(seconds=off_s)
            self._record_action(f"Heater OFF · night pulse end -> cooldown {off_s}s")
            ctx.heater_on = False

    # ------------------------------------------------------------------ #
    #  Day hard limits                                                     #
    # ------------------------------------------------------------------ #

    async def _apply_day_hard_limits(self, ctx: _Ctx) -> bool:
        """Returns True if a hard limit was active."""
        limit = self._eval_hard_limits(ctx)
        if limit is None:
            return False

        ctx.data["control_mode"] = f"hard_limit:{limit}"

        if limit == "temp_below_min":
            await self._heater_on_if_allowed(ctx, "hard_limit: temp_below_min -> heater_on")
            await self._exhaust_off_if_on(ctx, "hard_limit: temp_below_min -> exhaust_off")
        elif limit == "temp_above_max":
            await self._heater_off(ctx, "hard_limit: temp_above_max -> heater_off")
            await self._exhaust_on_if_off(ctx, "hard_limit: temp_above_max -> exhaust_on")
        elif limit == "rh_above_max":
            if ctx.avg_temp > ctx.min_temp:
                await self._exhaust_on_if_off(ctx, "hard_limit: rh_above_max -> exhaust_on")
            if ctx.avg_temp >= ctx.min_temp:
                await self._heater_off(ctx, "hard_limit: rh_above_max -> heater_off")
            await self._humidifier_off(ctx)
            await self._dehumidifier_on(ctx)
        elif limit == "rh_below_min":
            await self._exhaust_off_if_on(ctx, "hard_limit: rh_below_min -> exhaust_off")
            if ctx.avg_temp > ctx.min_temp:
                await self._heater_off(ctx, "hard_limit: rh_below_min -> heater_off")
            await self._dehumidifier_off(ctx)
            await self._humidifier_on(ctx)

        return True

    # ------------------------------------------------------------------ #
    #  VPD chase                                                           #
    # ------------------------------------------------------------------ #

    async def _apply_vpd_chase(self, ctx: _Ctx) -> None:
        ctx.data["control_mode"] = "vpd_chase"
        target_vpd = float(ctx.data.get("vpd_target_kpa", STAGE_TARGET_VPD_KPA.get(ctx.stage, 1.00)))
        deadband   = float(ctx.data.get("vpd_deadband_kpa", 0.07))
        low  = target_vpd - deadband
        high = target_vpd + deadband

        if ctx.vpd < low:
            await self._dehumidifier_on(ctx)
            ctx.data["debug_dehumidifier_reason"] = "vpd_low -> on"
            await self._humidifier_off(ctx)
            ctx.data["debug_humidifier_reason"] = "vpd_low -> off"
            if ctx.avg_temp < (ctx.max_temp - 0.2):
                await self._heater_on_if_allowed(ctx, "vpd_low: temp has room -> heater_on")
                await self._exhaust_off_if_on(ctx, "vpd_low: temp has room -> exhaust_off")
            elif ctx.avg_rh > (ctx.min_rh + 1.0):
                await self._exhaust_on_if_off(ctx, "vpd_low: temp near max -> exhaust_on")

        elif ctx.vpd > high:
            await self._dehumidifier_off(ctx)
            await self._humidifier_on(ctx)
            ctx.data["debug_humidifier_reason"] = "vpd_high -> on"
            await self._heater_off(ctx, "vpd_high -> heater_off")
            await self._exhaust_off_if_on(ctx, "vpd_high -> exhaust_off")

        else:
            await self._humidifier_off(ctx)
            await self._dehumidifier_off(ctx)
            await self._heater_off(ctx, "vpd_inband -> heater_off")
            await self._exhaust_off_if_on(ctx, "vpd_inband -> exhaust_off")

    # ------------------------------------------------------------------ #
    #  Hard limit evaluator                                                #
    # ------------------------------------------------------------------ #

    def _eval_hard_limits(self, ctx: _Ctx) -> str | None:
        if ctx.avg_temp < ctx.min_temp: return "temp_below_min"
        if ctx.avg_temp > ctx.max_temp: return "temp_above_max"
        if ctx.avg_rh   < ctx.min_rh:  return "rh_below_min"
        if ctx.avg_rh   > ctx.max_rh:  return "rh_above_max"
        return None

    # ------------------------------------------------------------------ #
    #  Atomic device action helpers                                        #
    # ------------------------------------------------------------------ #

    async def _heater_off(self, ctx: _Ctx, reason: str) -> None:
        ctx.data["debug_heater_reason"] = reason
        if ctx.heater_on and ctx.heater_eid and self._can_toggle(self.control.last_heater_change, ctx.heater_hold):
            await self._async_switch(ctx.heater_eid, False)
            self.control.last_heater_change = ctx.now
            self._record_action(f"Heater OFF · {reason}")
            ctx.heater_on = False

    async def _heater_on_if_allowed(self, ctx: _Ctx, reason: str) -> None:
        ctx.data["debug_heater_reason"] = reason
        if (
            not ctx.heater_on and ctx.heater_eid
            and self._heater_allowed_on(ctx.now)
            and self._can_toggle(self.control.last_heater_change, ctx.heater_hold)
        ):
            await self._async_switch(ctx.heater_eid, True)
            self.control.last_heater_change = ctx.now
            self._record_action(f"Heater ON · {reason}")
            ctx.heater_on = True

    async def _exhaust_on_if_off(self, ctx: _Ctx, reason: str) -> None:
        ctx.data["debug_exhaust_reason"] = reason
        if not ctx.exhaust_on and ctx.exhaust_eid and self._can_toggle(self.control.last_exhaust_change, ctx.exhaust_hold):
            await self._async_switch(ctx.exhaust_eid, True)
            self.control.last_exhaust_change = ctx.now
            self._record_action(f"Exhaust ON · {reason}")
            ctx.exhaust_on = True

    async def _exhaust_off_if_on(self, ctx: _Ctx, reason: str) -> None:
        ctx.data["debug_exhaust_reason"] = reason
        if ctx.exhaust_on and ctx.exhaust_eid and self._can_toggle(self.control.last_exhaust_change, ctx.exhaust_hold):
            await self._async_switch(ctx.exhaust_eid, False)
            self.control.last_exhaust_change = ctx.now
            self._record_action(f"Exhaust OFF · {reason}")
            ctx.exhaust_on = False

    async def _humidifier_on(self, ctx: _Ctx, reason: str = "auto") -> None:
        if not ctx.humidifier_on and ctx.humidifier_eid and self._can_toggle(self.control.last_humidifier_change, ctx.humidifier_hold):
            await self._async_switch(ctx.humidifier_eid, True)
            self.control.last_humidifier_change = ctx.now
            self._record_action(f"Humidifier ON · {reason}")
            ctx.humidifier_on = True

    async def _humidifier_off(self, ctx: _Ctx, reason: str = "auto") -> None:
        if ctx.humidifier_on and ctx.humidifier_eid and self._can_toggle(self.control.last_humidifier_change, ctx.humidifier_hold):
            await self._async_switch(ctx.humidifier_eid, False)
            self.control.last_humidifier_change = ctx.now
            self._record_action(f"Humidifier OFF · {reason}")
            ctx.humidifier_on = False

    async def _dehumidifier_on(self, ctx: _Ctx, reason: str = "auto") -> None:
        if not ctx.dehumidifier_on and ctx.dehumidifier_eid and self._can_toggle(self.control.last_dehumidifier_change, ctx.dehumidifier_hold):
            await self._async_switch(ctx.dehumidifier_eid, True)
            self.control.last_dehumidifier_change = ctx.now
            self._record_action(f"Dehumidifier ON · {reason}")
            ctx.dehumidifier_on = True

    async def _dehumidifier_off(self, ctx: _Ctx, reason: str = "auto") -> None:
        if ctx.dehumidifier_on and ctx.dehumidifier_eid and self._can_toggle(self.control.last_dehumidifier_change, ctx.dehumidifier_hold):
            await self._async_switch(ctx.dehumidifier_eid, False)
            self.control.last_dehumidifier_change = ctx.now
            self._record_action(f"Dehumidifier OFF · {reason}")
            ctx.dehumidifier_on = False

    # ------------------------------------------------------------------ #
    #  Top-level control dispatcher                                        #
    # ------------------------------------------------------------------ #

    async def _apply_control(self, data: dict[str, Any]) -> dict[str, Any]:
        enabled: bool = data.get("controller_enabled", True)
        stage:   str  = data.get("stage", DEFAULT_STAGE)
        drying:  bool = stage == "Drying"

        light_on  = data.get("light_on_time")
        light_off = data.get("light_off_time")
        if not isinstance(light_on,  time): light_on  = _DEFAULT_LIGHT_ON
        if not isinstance(light_off, time): light_off = _DEFAULT_LIGHT_OFF

        now   = self._now()
        now_t = dt_util.as_local(now).time()
        is_day = self._is_time_between(now_t, light_on, light_off)

        if drying:
            is_day = False
            data["debug_light_window"] = (
                f"{light_on.strftime('%H:%M:%S')}–{light_off.strftime('%H:%M:%S')} (ignored: drying)"
            )
        else:
            data["debug_light_window"] = f"{light_on.strftime('%H:%M:%S')}–{light_off.strftime('%H:%M:%S')}"
        data["debug_is_day"] = is_day

        light_eid        = self._get_option(CONF_LIGHT_SWITCH)        if self._use(CONF_USE_LIGHT)         else None
        circ_eid         = self._get_option(CONF_CIRC_SWITCH)         if self._use(CONF_USE_CIRCULATION)   else None
        exhaust_eid      = self._get_option(CONF_EXHAUST_SWITCH)      if self._use(CONF_USE_EXHAUST)        else None
        heater_eid       = self._get_option(CONF_HEATER_SWITCH)       if self._use(CONF_USE_HEATER)         else None
        humidifier_eid   = self._get_option(CONF_HUMIDIFIER_SWITCH)   if self._use(CONF_USE_HUMIDIFIER)     else None
        dehumidifier_eid = self._get_option(CONF_DEHUMIDIFIER_SWITCH) if self._use(CONF_USE_DEHUMIDIFIER)   else None

        # --- Light ---
        light_mode = self._get_mode("light_mode") if light_eid else "Auto"
        cur_light  = self._switch_is_on(light_eid)
        if light_mode != "Auto":
            desired = light_mode == "On"
            data["debug_light_reason"] = f"override:{light_mode.lower()}"
            if light_eid and cur_light is not None and cur_light != desired:
                await self._async_switch(light_eid, desired)
                self.control.last_light_change = now
                self._record_action(f"Light {'ON' if desired else 'OFF'} · override:{light_mode.lower()}")
        elif light_eid and cur_light is not None:
            if drying:
                data["debug_light_reason"] = "drying -> force_off"
                if cur_light and self._can_toggle(self.control.last_light_change, 10):
                    await self._async_switch(light_eid, False)
                    self.control.last_light_change = now
                    self._record_action("Light OFF · drying")
            elif not is_day and cur_light:
                data["debug_light_reason"] = "schedule_night_window -> turn_off"
                if self._can_toggle(self.control.last_light_change, 10):
                    await self._async_switch(light_eid, False)
                    self.control.last_light_change = now
                    self._record_action("Light OFF · schedule night window")
            elif is_day and not cur_light:
                data["debug_light_reason"] = "schedule_day_window -> turn_on"
                if self._can_toggle(self.control.last_light_change, 10):
                    await self._async_switch(light_eid, True)
                    self.control.last_light_change = now
                    self._record_action("Light ON · schedule day window")
            else:
                data["debug_light_reason"] = "schedule_ok -> no_change"
        elif not light_eid:
            data["debug_light_reason"] = "light_entity_not_configured"
        else:
            data["debug_light_reason"] = "light_state_unknown"

        # --- Circulation ---
        circ_mode = self._get_mode("circulation_mode") if circ_eid else "Auto"
        if circ_mode != "Auto" and circ_eid:
            desired = circ_mode == "On"
            data["debug_circulation_reason"] = f"override:{circ_mode.lower()}"
            cur = self._switch_is_on(circ_eid)
            if cur is not None and cur != desired:
                await self._async_switch(circ_eid, desired)
                self._record_action(f"Circulation {'ON' if desired else 'OFF'} · override:{circ_mode.lower()}")
        elif enabled and circ_eid:
            cur = self._switch_is_on(circ_eid)
            if cur is not None and not cur:
                await self._async_switch(circ_eid, True)
                self._record_action("Circulation ON · controller enabled")

        # --- Controller disabled ---
        if not enabled:
            data["control_mode"] = "disabled"
            for eid, mode_key, label in [
                (heater_eid, "heater_mode", "Heater"),
                (exhaust_eid, "exhaust_mode", "Exhaust"),
                (humidifier_eid, "humidifier_mode", "Humidifier"),
                (dehumidifier_eid, "dehumidifier_mode", "Dehumidifier"),
            ]:
                if not eid:
                    continue
                mode = self._get_mode(mode_key)
                if mode == "Auto":
                    continue
                desired = mode == "On"
                if label == "Exhaust" and mode == "Off":
                    avg_t = data.get("avg_temp_c")
                    avg_r = data.get("avg_rh")
                    if avg_t is not None and avg_r is not None:
                        if (float(avg_t) >= float(data.get("exhaust_safety_max_temp_c", 30.0)) or
                                float(avg_r) >= float(data.get("exhaust_safety_max_rh", 75.0))):
                            desired = True
                cur_s = self._switch_is_on(eid)
                if cur_s is not None and cur_s != desired:
                    await self._async_switch(eid, desired)
                    self._record_action(f"{label} {'ON' if desired else 'OFF'} · override:{mode.lower()} (disabled)")
            return data

        # --- Read actual hardware states BEFORE forced overrides ---
        heater_on_actual = self._switch_is_on(heater_eid) is True
        exhaust_on       = self._switch_is_on(exhaust_eid) is True
        humidifier_on    = self._switch_is_on(humidifier_eid) is True
        dehumidifier_on  = self._switch_is_on(dehumidifier_eid) is True

        # Heater on-time tracking (must use real hardware state)
        if heater_on_actual:
            if self.control.heater_on_since is None:
                self.control.heater_on_since = now
        else:
            self.control.heater_on_since = None

        data["debug_heater_on_for_s"] = (
            int((now - self.control.heater_on_since).total_seconds())
            if heater_on_actual and self.control.heater_on_since else 0
        )

        # Build context
        ctx = _Ctx(
            data               = data,
            now                = now,
            stage              = stage,
            drying             = drying,
            is_day             = is_day,
            avg_temp           = float(data.get("avg_temp_c") or 0.0),
            avg_rh             = float(data.get("avg_rh")     or 0.0),
            dew                = float(data.get("dew_point_c") or 0.0),
            vpd                = float(data.get("vpd_kpa")     or 0.0),
            min_temp           = float(data.get("min_temp_c", 20.0)),
            max_temp           = float(data.get("max_temp_c", 30.0)),
            min_rh             = float(data.get("min_rh",     40.0)),
            max_rh             = float(data.get("max_rh",     70.0)),
            dew_margin         = float(data.get("dewpoint_margin_c", 1.0)),
            heater_hold        = float(data.get("heater_hold_s",      60.0)),
            exhaust_hold       = float(data.get("exhaust_hold_s",     45.0)),
            humidifier_hold    = float(data.get("humidifier_hold_s",  45.0)),
            dehumidifier_hold  = float(data.get("dehumidifier_hold_s",45.0)),
            exhaust_eid        = exhaust_eid,
            heater_eid         = heater_eid,
            humidifier_eid     = humidifier_eid,
            dehumidifier_eid   = dehumidifier_eid,
            heater_on          = heater_on_actual,
            exhaust_on         = exhaust_on,
            humidifier_on      = humidifier_on,
            dehumidifier_on    = dehumidifier_on,
            exhaust_safety_on  = bool(data.get("exhaust_safety_override")),
            exhaust_safety_max_temp = float(data.get("exhaust_safety_max_temp_c", 30.0)),
            exhaust_safety_max_rh   = float(data.get("exhaust_safety_max_rh",     75.0)),
            heater_max_run_s   = float(data.get("heater_max_run_s", 0.0) or 0.0),
        )

        # Apply forced On/Off overrides
        ctx = await self._apply_forced_modes(ctx)

        # Check sensors before proceeding
        sensors_ok = (
            data.get("avg_temp_c")  is not None and
            data.get("avg_rh")      is not None and
            data.get("dew_point_c") is not None and
            data.get("vpd_kpa")     is not None
        )
        self._handle_sensor_availability(sensors_ok)
        if not sensors_ok:
            data["control_mode"] = "waiting_for_sensors"
            return data

        # Heater safety before anything else
        if await self._apply_heater_safety(ctx):
            return data

        data["debug_exhaust_policy"] = "normal"

        if drying:
            await self._apply_drying_mode(ctx)
        elif not is_day:
            await self._apply_night_mode(ctx)
        else:
            hard_limit_active = await self._apply_day_hard_limits(ctx)
            if not hard_limit_active:
                if data.get("vpd_chase_enabled", True):
                    await self._apply_vpd_chase(ctx)
                else:
                    ctx.data["control_mode"] = "limits_only"

        return data

    # ------------------------------------------------------------------ #
    #  VPD target stage-reset                                             #
    # ------------------------------------------------------------------ #

    async def _reset_vpd_target_for_stage(self, stage: str) -> None:
        """Find the VpdTargetNumber entity and reset it to the stage default."""
        from homeassistant.helpers.entity_component import EntityComponent
        target_uid = f"{self.entry.entry_id}_vpd_target_kpa"
        component: EntityComponent | None = self.hass.data.get("entity_components", {}).get("number")
        if component is None:
            return
        for entity in component.entities:
            if getattr(entity, "unique_id", None) == target_uid:
                await entity.async_set_to_stage_default(stage)
                _LOGGER.debug(
                    "VPD target reset to %.2f kPa for stage: %s",
                    STAGE_TARGET_VPD_KPA.get(stage, 1.00),
                    stage,
                )
                return

    # ------------------------------------------------------------------ #
    #  Main data update                                                    #
    # ------------------------------------------------------------------ #

    async def _async_update_data(self) -> dict[str, Any]:
        canopy_t  = self._get_state_float(self._get_option(CONF_CANOPY_TEMP))
        top_t     = self._get_state_float(self._get_option(CONF_TOP_TEMP))
        canopy_rh = self._get_state_float(self._get_option(CONF_CANOPY_RH))
        top_rh    = self._get_state_float(self._get_option(CONF_TOP_RH))

        avg_t = avg([canopy_t, top_t])
        avg_r = avg([canopy_rh, top_rh])

        leaf_off_eid  = self._entity_id("number", "leaf_temp_offset_c")
        leaf_offset_c = self._num(leaf_off_eid, 0.0)

        vpd = dew = leaf_temp_c = None
        if avg_t is not None and avg_r is not None:
            leaf_temp_c = avg_t + float(leaf_offset_c)
            vpd = vpd_leaf_kpa(avg_t, avg_r, leaf_temp_c)
            dew = dew_point_c(avg_t, avg_r)

        controller_eid = self._entity_id("switch", "controller")
        stage_eid      = self._entity_id("select", "stage")

        now_local        = dt_util.as_local(self._now())
        debug_local_time = now_local.strftime("%Y-%m-%d %H:%M:%S")
        debug_local_tod  = now_local.strftime("%H:%M:%S")

        enabled_state      = self._get_entity_state(controller_eid)
        controller_enabled = (enabled_state == "on") if enabled_state is not None else True
        stage_state        = self._get_entity_state(stage_eid)
        stage              = stage_state if stage_state in STAGE_TARGET_VPD_KPA else DEFAULT_STAGE

        def _eid(key: str, domain: str = "number") -> str:
            return self._entity_id(domain, key)

        data: dict[str, Any] = {
            "canopy_temp_c":   canopy_t,
            "top_temp_c":      top_t,
            "canopy_rh":       canopy_rh,
            "top_rh":          top_rh,
            "avg_temp_c":      avg_t,
            "avg_rh":          avg_r,
            "vpd_kpa":         vpd,
            "dew_point_c":     dew,
            "controller_enabled": controller_enabled,
            "stage":              stage,
            "min_temp_c":         self._num(_eid("min_temp_c"),         20.0),
            "max_temp_c":         self._num(_eid("max_temp_c"),         30.0),
            "min_rh":             self._num(_eid("min_rh"),             40.0),
            "max_rh":             self._num(_eid("max_rh"),             70.0),
            "vpd_target_kpa":     self._num(_eid("vpd_target_kpa"),     1.00),
            "vpd_deadband_kpa":   self._num(_eid("vpd_deadband_kpa"),   0.07),
            "vpd_chase_enabled":  (self._get_entity_state(_eid("vpd_chase_enabled", "switch")) != "off"),
            "dewpoint_margin_c":  self._num(_eid("dewpoint_margin_c"),  1.0),
            "heater_hold_s":      self._num(_eid("heater_hold_s"),      60.0),
            "exhaust_hold_s":     self._num(_eid("exhaust_hold_s"),     45.0),
            "humidifier_hold_s":  self._num(_eid("humidifier_hold_s"),  45.0),
            "dehumidifier_hold_s":self._num(_eid("dehumidifier_hold_s"),45.0),
            "exhaust_safety_override":   (self._get_entity_state(_eid(CONF_EXHAUST_SAFETY_OVERRIDE, "switch")) == "on"),
            "exhaust_safety_max_temp_c": self._num(_eid(CONF_EXHAUST_SAFETY_MAX_TEMP_C), 30.0),
            "exhaust_safety_max_rh":     self._num(_eid(CONF_EXHAUST_SAFETY_MAX_RH),     75.0),
            "heater_max_run_s":          self._num(_eid("heater_max_run_s"),              0.0),
            "light_on_time":   self._parse_time(self._get_entity_state(_eid("light_on",  "time")), _DEFAULT_LIGHT_ON),
            "light_off_time":  self._parse_time(self._get_entity_state(_eid("light_off", "time")), _DEFAULT_LIGHT_OFF),
            "control_mode":    "init",
            "leaf_temp_offset_c":  float(leaf_offset_c),
            "leaf_temp_c":         leaf_temp_c,
            # New in v0.1.15
            "last_action":         self.control.last_action,
            "sensors_unavailable": self.control.sensors_were_unavailable,
            # Debug
            "debug_local_time":       debug_local_time,
            "debug_local_tod":        debug_local_tod,
            "debug_light_reason":     "n/a",
            "debug_exhaust_policy":   "n/a",
            "debug_exhaust_reason":   "n/a",
            "debug_heater_reason":    "n/a",
            "debug_heater_target_c":  None,
            "debug_heater_error_c":   None,
            "debug_heater_on_for_s":  0,
            "debug_heater_max_run_s": 0.0,
            "debug_heater_lockout":   "inactive",
        }

        data = await self._apply_control(data)

        # Stage-change detection: reset VPD target to stage default when stage changes
        current_stage = data.get("stage", DEFAULT_STAGE)
        if current_stage != self.control.last_stage:
            self.control.last_stage = current_stage
            await self._reset_vpd_target_for_stage(current_stage)

        return data
