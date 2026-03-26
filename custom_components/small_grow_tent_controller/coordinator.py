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

from .climate_math import safe_float, avg, dew_point_c, vpd_leaf_kpa, sat_vapor_pressure_kpa
from .const import (
    DOMAIN,
    DEFAULT_STAGE,
    STAGE_TARGET_VPD_KPA,
    STAGE_NIGHT_TARGET_TEMP_C,
    STAGE_NIGHT_TARGET_VPD_KPA,
    STAGE_NIGHT_TARGET_RH,
    CONF_NIGHT_MODE,
    NIGHT_MODE_VPD,
    NIGHT_MODE_VPD_NO_HEATER,
    EXHAUST_MODE_DAY_ON,
    EXHAUST_MODE_NIGHT_ON,
    CONF_DAY_MODE,
    DAY_MODE_MPC,
    DAY_MODE_LIMITS,
    STAGE_TARGET_TEMP_C,
    STAGE_TARGET_RH,
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
    "Seedling":          {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Early Vegetative":  {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Late Vegetative":   {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Early Bloom":       {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Late Bloom":        {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Drying":            {"exhaust_mode": "on",   "dew_margin_add_c": 1.0},
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

    # Suppress sensor-unavailable warning/notification on the very first poll
    # cycle after startup — sensors are routinely unavailable for a few seconds
    # while HA initialises, and logging at that point is misleading noise.
    is_first_poll: bool = True

    # Stage change detection (for VPD target auto-reset)
    last_stage: str = ""

    # Day/night transition tracking for temperature ramp
    last_is_day: bool | None = None
    # Effective ramped temperature target (°C) — slides toward actual target at ramp rate
    ramped_target_temp_c: float | None = None

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
    circ_eid:           str | None
    heater_on:          bool
    exhaust_on:         bool
    humidifier_on:      bool
    dehumidifier_on:    bool
    circ_on:            bool
    exhaust_safety_on:  bool
    exhaust_safety_max_temp: float
    exhaust_safety_max_rh:   float
    heater_max_run_s:   float
    night_mode:         str
    night_vpd_target:   float
    night_target_temp:  float
    night_target_rh:    float
    temp_ramp_rate:     float
    day_mode:           str
    # MPC model parameters
    mpc_horizon:        int
    mpc_temp_amb:       float
    mpc_rh_amb:         float
    mpc_a_heater:       float
    mpc_a_exhaust:      float
    mpc_a_passive:      float
    mpc_a_bias:         float
    mpc_b_exhaust:      float
    mpc_b_passive:      float
    mpc_b_bias:         float
    mpc_w_vpd:          float
    mpc_w_temp:         float
    mpc_w_rh:           float
    mpc_w_switch:       float


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
        return st.state if st.state in ("Auto", "On", "Off", "Day On", "Night On") else "Auto"

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
    #  Temperature ramp helper                                             #
    # ------------------------------------------------------------------ #

    def _apply_temp_ramp(self, effective_target: float, actual_target: float, ramp_rate: float) -> float:
        """Slide effective_target toward actual_target at no more than ramp_rate °C/poll.

        ramp_rate is in °C/min; the controller polls every 10 seconds so the
        per-poll cap is ramp_rate * 10/60.  When ramp_rate is 0 the target
        jumps immediately (ramp disabled).
        """
        if ramp_rate <= 0:
            return actual_target
        max_delta = ramp_rate * (10.0 / 60.0)   # °C per 10-second poll
        delta = actual_target - effective_target
        if abs(delta) <= max_delta:
            return actual_target
        return effective_target + (max_delta if delta > 0 else -max_delta)

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
                # Suppress the warning and persistent notification on the very
                # first poll after startup — sensors are routinely unavailable
                # for a few seconds while HA initialises its entity registry.
                # This avoids misleading "sensors unavailable" noise in the log
                # and on the dashboard every time HASS restarts.
                if not self.control.is_first_poll:
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

        # Clear the first-poll flag regardless of sensor state — from this
        # point on, any sensor dropout is a genuine runtime event.
        self.control.is_first_poll = False

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
            ("circ_eid",         "circulation_mode",  "Circulation",  None,                "circ_on"),
        ]:
            eid  = getattr(ctx, eid_attr)
            mode = self._get_mode(mode_key) if eid else "Auto"
            if mode == "Auto" or not eid:
                continue
            desired = mode == "On"
            cur = self._switch_is_on(eid)
            if cur is not None and cur != desired:
                await self._async_switch(eid, desired)
                if hold_attr:
                    setattr(self.control, f"last_{label.lower()}_change", now)
                self._record_action(f"{label} {'ON' if desired else 'OFF'} · override:{mode.lower()}")
            setattr(ctx, on_attr, desired)
            setattr(ctx, eid_attr, None)

        # Exhaust: special safety check + Day On / Night On schedule modes
        # Day On / Night On force the exhaust on during their window only.
        # Outside their window they fall back to Auto — the normal control
        # logic runs as if the mode were set to Auto.
        eid  = ctx.exhaust_eid
        mode = self._get_mode("exhaust_mode") if eid else "Auto"
        if mode != "Auto" and eid:
            if mode == "Day On":
                if ctx.is_day:
                    # In window — force on
                    reason = "override:day_on (day window)"
                    if self._exhaust_safety_blocks_off(ctx) or True:  # desired=True always here
                        pass
                    ctx.data["debug_exhaust_reason"] = reason
                    cur = self._switch_is_on(eid)
                    if cur is not None and not cur:
                        await self._async_switch(eid, True)
                        self.control.last_exhaust_change = now
                        self._record_action(f"Exhaust ON · {reason}")
                    ctx.exhaust_on  = True
                    ctx.exhaust_eid = None  # handled — skip auto
                else:
                    # Outside window — fall through to auto control
                    ctx.data["debug_exhaust_reason"] = "day_on: night window -> auto"
                    # ctx.exhaust_eid left intact — auto logic runs
            elif mode == "Night On":
                if not ctx.is_day:
                    # In window — force on
                    reason = "override:night_on (night window)"
                    ctx.data["debug_exhaust_reason"] = reason
                    cur = self._switch_is_on(eid)
                    if cur is not None and not cur:
                        await self._async_switch(eid, True)
                        self.control.last_exhaust_change = now
                        self._record_action(f"Exhaust ON · {reason}")
                    ctx.exhaust_on  = True
                    ctx.exhaust_eid = None  # handled — skip auto
                else:
                    # Outside window — fall through to auto control
                    ctx.data["debug_exhaust_reason"] = "night_on: day window -> auto"
                    # ctx.exhaust_eid left intact — auto logic runs
            else:
                # On / Off hard override
                desired = mode == "On"
                reason  = f"override:{mode.lower()}"
                # Safety always overrides — exhaust cannot be turned off if safety blocks it
                if not desired and self._exhaust_safety_blocks_off(ctx):
                    desired = True
                    reason  += " [SAFETY: blocked_off]"
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
    #  Night VPD Chase mode                                                #
    # ------------------------------------------------------------------ #

    async def _apply_night_vpd_chase(self, ctx: _Ctx) -> None:
        """VPD chase at night with a dew-point floor.

        Runs the standard day VPD chase logic, then enforces a hard dew-point
        floor: if the chase would leave the heater off but the tent temperature
        is at or below dew + margin, the heater is turned on to prevent
        condensation regardless of what VPD chase decided.

        When heater mode is "Night Off", the heater eid is suppressed during
        the VPD chase pass so it plays no part in chasing VPD. It is restored
        before the dew floor check so condensation protection is always active.

        The stage night exhaust profile (on / auto) is also still applied so
        that exhaust behaviour at night is consistent with the dew-protection
        mode and the user's per-stage configuration.
        """
        profile      = STAGE_NIGHT_PROFILE.get(ctx.stage, {"exhaust_mode": "on", "dew_margin_add_c": 0.0})
        exhaust_mode = profile.get("exhaust_mode", "on")
        dew_margin_night = ctx.dew_margin + float(profile.get("dew_margin_add_c", 0.0))
        dew_floor = ctx.dew + dew_margin_night

        ctx.data["control_mode"] = "night_vpd_chase"

        # "VPD Chase (No Heater)" night mode: suppress heater from VPD chase
        # but keep the eid aside so the dew floor check can still use it.
        night_heater_suppressed = (ctx.night_mode == NIGHT_MODE_VPD_NO_HEATER)
        saved_heater_eid = ctx.heater_eid
        if night_heater_suppressed:
            ctx.heater_eid = None
            ctx.data["debug_heater_reason"] = "night_vpd_chase: VPD Chase (No Heater) — heater suppressed for VPD chase"

        # Run standard VPD chase (handles heater, exhaust, humidifier, dehumidifier)
        await self._apply_vpd_chase(ctx)

        # Restore heater eid before dew floor check so condensation protection
        # is always active regardless of Night Off setting.
        if night_heater_suppressed:
            ctx.heater_eid = saved_heater_eid

        # Dew-point floor: override heater if VPD chase left it off but we are
        # too close to (or below) the dew point.
        if not ctx.heater_on and ctx.avg_temp <= dew_floor:
            ctx.data["debug_heater_reason"] = (
                f"night_vpd_chase: dew floor override "
                f"(avg={ctx.avg_temp:.1f}°C <= floor={dew_floor:.1f}°C)"
                + (" [Night Off: dew only]" if night_heater_suppressed else "")
            )
            await self._heater_on_if_allowed(
                ctx, f"night VPD chase: dew floor {dew_floor:.1f}°C"
            )

        # Apply stage exhaust night profile on top of VPD chase exhaust decision
        if exhaust_mode == "on":
            ctx.data["debug_exhaust_reason"] = (
                ctx.data.get("debug_exhaust_reason", "") + " [night profile: force_on]"
            )
            await self._exhaust_on_if_off(ctx, "night VPD chase: profile=on")
        elif exhaust_mode == "auto":
            want = ctx.avg_rh > ctx.max_rh or ctx.avg_temp > ctx.max_temp
            if not want:
                await self._exhaust_off_if_on(ctx, "night VPD chase: profile=auto, conditions_ok")

        # ------------------------------------------------------------------ #
    #  MPC day control                                                     #
    # ------------------------------------------------------------------ #

    def _mpc_simulate(
        self,
        temp0: float, rh0: float,
        actions: list[tuple[int, int]],   # list of (heater, exhaust) per step
        ctx: "_Ctx",
    ) -> tuple[float, float]:
        """Simulate tent state forward using the identified model."""
        temp = temp0
        rh   = rh0
        ta   = ctx.mpc_temp_amb
        ra   = ctx.mpc_rh_amb
        for h, e in actions:
            temp += (ctx.mpc_a_heater  * h
                   + ctx.mpc_a_exhaust * e
                   + ctx.mpc_a_passive * (ta - temp)
                   + ctx.mpc_a_bias)
            rh   += (ctx.mpc_b_exhaust * e
                   + ctx.mpc_b_passive * (ra - rh)
                   + ctx.mpc_b_bias)
            # Clamp to physically plausible range
            temp = max(0.0,   min(60.0, temp))
            rh   = max(0.1,   min(99.9, rh))
        return temp, rh

    def _mpc_score(
        self,
        temp_final: float, rh_final: float,
        target_temp: float, target_rh: float, target_vpd: float,
        actions: list[tuple[int, int]],
        heater_on_now: bool, exhaust_on_now: bool,
        ctx: "_Ctx",
    ) -> float:
        """Score a candidate action sequence. Lower = better."""
        # Compute implied VPD at predicted state
        leaf_temp = temp_final + float(ctx.data.get("leaf_temp_offset_c", -1.5))
        pred_vpd  = vpd_leaf_kpa(temp_final, rh_final, leaf_temp)

        temp_err = (temp_final  - target_temp) ** 2
        rh_err   = (rh_final    - target_rh)   ** 2
        vpd_err  = (pred_vpd    - target_vpd)  ** 2

        # Switching penalty: penalise changing device state on first step
        first_h, first_e = actions[0]
        switch_penalty = (
            (abs(first_h - int(heater_on_now)) + abs(first_e - int(exhaust_on_now)))
            * ctx.mpc_w_switch
        )

        return (ctx.mpc_w_vpd  * vpd_err
              + ctx.mpc_w_temp * temp_err
              + ctx.mpc_w_rh   * rh_err
              + switch_penalty)

    @staticmethod
    def _mpc_optimise(
        temp0: float, rh0: float,
        heater_on: bool, exhaust_on: bool,
        target_temp: float, target_rh: float, target_vpd: float,
        horizon: int,
        leaf_offset: float,
        mpc_temp_amb: float, mpc_rh_amb: float,
        mpc_a_heater: float, mpc_a_exhaust: float,
        mpc_a_passive: float, mpc_a_bias: float,
        mpc_b_exhaust: float, mpc_b_passive: float, mpc_b_bias: float,
        mpc_w_vpd: float, mpc_w_temp: float, mpc_w_rh: float, mpc_w_switch: float,
    ) -> tuple[int, int, float, list, float, float, float]:
        """Pure CPU work — runs in a thread pool, must not touch HA state.

        Returns (h_want, e_want, best_score, best_actions, pred_temp, pred_rh, pred_vpd).
        """
        import math

        def sim(actions):
            temp = temp0
            rh   = rh0
            for h, e in actions:
                temp += mpc_a_heater * h + mpc_a_exhaust * e + mpc_a_passive * (mpc_temp_amb - temp) + mpc_a_bias
                rh   += mpc_b_exhaust * e + mpc_b_passive * (mpc_rh_amb - rh)   + mpc_b_bias
                temp = max(0.0, min(60.0, temp))
                rh   = max(0.1, min(99.9, rh))
            return temp, rh

        def vpd_leaf(air_t, rh_pct, leaf_t):
            avp = (rh_pct / 100.0) * 0.6108 * math.exp(17.27 * air_t / (air_t + 237.3))
            return max(0.0, 0.6108 * math.exp(17.27 * leaf_t / (leaf_t + 237.3)) - avp)

        best_score   = float("inf")
        best_actions = [(0, 0)] * horizon

        for combo_idx in range(4 ** horizon):
            actions = []
            idx = combo_idx
            for _ in range(horizon):
                bit = idx % 4
                idx //= 4
                actions.append((1 if bit >= 2 else 0, 1 if bit % 2 == 1 else 0))

            tf, rf = sim(actions)
            lf = tf + leaf_offset
            pv = vpd_leaf(tf, rf, lf)

            first_h, first_e = actions[0]
            switch_pen = (abs(first_h - int(heater_on)) + abs(first_e - int(exhaust_on))) * mpc_w_switch
            score = (mpc_w_vpd  * (pv - target_vpd)  ** 2
                   + mpc_w_temp * (tf - target_temp)  ** 2
                   + mpc_w_rh   * (rf - target_rh)    ** 2
                   + switch_pen)

            if score < best_score:
                best_score   = score
                best_actions = actions

        tf, rf = sim(best_actions)
        lf = tf + leaf_offset
        pv = vpd_leaf(tf, rf, lf)
        h_want, e_want = best_actions[0]
        return h_want, e_want, best_score, best_actions, tf, rf, pv

    async def _apply_mpc_day(self, ctx: "_Ctx") -> None:
        """MPC day control.

        Evaluates all combinations of heater/exhaust states over a planning
        horizon, simulates tent temperature and RH forward using the identified
        first-order model, and selects the sequence that minimises a weighted
        cost function combining VPD error, temperature error, RH error, and
        a device switching penalty.

        The combinatorial search runs in a thread-pool executor so it never
        blocks the HA event loop. Only the first step of the optimal sequence
        is executed. Hard limits and hold times are still enforced.
        """
        ctx.data["control_mode"] = "mpc"

        # Targets: always use day targets in this method
        target_vpd  = float(ctx.data.get("vpd_target_kpa",  STAGE_TARGET_VPD_KPA.get(ctx.stage, 1.00)))
        target_temp = float(ctx.data.get("target_temp_c",   STAGE_TARGET_TEMP_C.get(ctx.stage, 25.0)))
        target_rh   = float(ctx.data.get("target_rh",       STAGE_TARGET_RH.get(ctx.stage, 55.0)))

        # Hard cap horizon at 6: 4^6 = 4096 combos, runs in <1ms in a thread
        horizon = max(1, min(6, int(ctx.mpc_horizon)))
        if ctx.mpc_horizon > 6:
            _LOGGER.debug(
                "%s: MPC horizon capped at 6 (configured %d) — 4^N grows exponentially",
                self.entry.title, ctx.mpc_horizon,
            )

        leaf_offset = float(ctx.data.get("leaf_temp_offset_c", -1.5))

        # Run the CPU-intensive optimisation off the event loop
        (h_want, e_want, best_score, best_actions,
         temp_pred, rh_pred, vpd_pred) = await self.hass.async_add_executor_job(
            self._mpc_optimise,
            ctx.avg_temp, ctx.avg_rh,
            ctx.heater_on, ctx.exhaust_on,
            target_temp, target_rh, target_vpd,
            horizon, leaf_offset,
            ctx.mpc_temp_amb, ctx.mpc_rh_amb,
            ctx.mpc_a_heater, ctx.mpc_a_exhaust,
            ctx.mpc_a_passive, ctx.mpc_a_bias,
            ctx.mpc_b_exhaust, ctx.mpc_b_passive, ctx.mpc_b_bias,
            ctx.mpc_w_vpd, ctx.mpc_w_temp, ctx.mpc_w_rh, ctx.mpc_w_switch,
        )

        # Predict where we'll be after horizon steps
        temp_pred, rh_pred = self._mpc_simulate(temp0, rh0, best_actions, ctx)
        leaf_pred = temp_pred + float(ctx.data.get("leaf_temp_offset_c", -1.5))
        vpd_pred  = vpd_leaf_kpa(temp_pred, rh_pred, leaf_pred)

        ctx.data["debug_mpc_horizon"]    = horizon
        ctx.data["debug_mpc_score"]      = round(best_score, 4)
        ctx.data["debug_mpc_pred_temp"]  = round(temp_pred, 2)
        ctx.data["debug_mpc_pred_rh"]    = round(rh_pred, 2)
        ctx.data["debug_mpc_pred_vpd"]   = round(vpd_pred, 3)
        ctx.data["debug_mpc_plan"]       = str(best_actions[:3])  # first 3 steps for debug

        # Heater: apply if hold time allows and safety permits
        if h_want == 1:
            await self._heater_on_if_allowed(ctx, f"mpc: plan={best_actions[:2]} score={best_score:.3f}")
        else:
            await self._heater_off(ctx, f"mpc: plan={best_actions[:2]} score={best_score:.3f}")

        # Exhaust: apply if hold time allows
        if e_want == 1:
            await self._exhaust_on_if_off(ctx, f"mpc: plan={best_actions[:2]}")
        else:
            await self._exhaust_off_if_on(ctx, f"mpc: plan={best_actions[:2]}")

        # Humidity devices: fall back to simple RH-deadband control since
        # we don't have a reliable humidifier model yet
        deadband_rh = 2.0
        if ctx.avg_rh < (target_rh - deadband_rh):
            await self._humidifier_on(ctx, "mpc: rh below target")
            await self._dehumidifier_off(ctx, "mpc: rh below target")
        elif ctx.avg_rh > (target_rh + deadband_rh):
            await self._humidifier_off(ctx, "mpc: rh above target")
            await self._reduce_humidity(ctx, "mpc: rh above target")
        else:
            await self._humidifier_off(ctx, "mpc: rh in band")
            await self._dehumidifier_off(ctx, "mpc: rh in band")

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
        # Use night targets during night window, day targets during day
        if ctx.is_day:
            target_vpd  = float(ctx.data.get("vpd_target_kpa",  STAGE_TARGET_VPD_KPA.get(ctx.stage, 1.00)))
            target_temp = float(ctx.data.get("target_temp_c",   STAGE_TARGET_TEMP_C.get(ctx.stage, 25.0)))
            target_rh   = float(ctx.data.get("target_rh",       STAGE_TARGET_RH.get(ctx.stage, 55.0)))
        else:
            target_vpd  = ctx.night_vpd_target
            target_temp = ctx.night_target_temp
            target_rh   = ctx.night_target_rh
        deadband    = float(ctx.data.get("vpd_deadband_kpa", 0.07))
        temp_db     = 0.5   # °C deadband around target temp before acting
        rh_db       = 2.0   # % RH deadband around target RH before acting
        low  = target_vpd - deadband
        high = target_vpd + deadband

        ctx.data["debug_target_temp_c"] = target_temp
        ctx.data["debug_target_rh"]     = target_rh

        if ctx.vpd < low:
            # VPD too low — air is too humid and/or too cold.
            # Priority: raise temperature toward target using heater.
            # Secondary: use dehumidifier if temp is already at/above target.
            if ctx.avg_temp < (target_temp - temp_db):
                # Temp below target — heater is the right tool
                await self._heater_on_if_allowed(ctx, "vpd_low: temp below target -> heater_on")
                await self._exhaust_off_if_on(ctx, "vpd_low: temp below target -> exhaust_off")
                await self._dehumidifier_off(ctx)
                ctx.data["debug_dehumidifier_reason"] = "vpd_low: heating -> dehumidifier_off"
                await self._humidifier_off(ctx)
                ctx.data["debug_humidifier_reason"] = "vpd_low: heating -> humidifier_off"
            elif ctx.avg_temp > (target_temp + temp_db):
                # Temp above target — exhaust to cool, dehumidifier to lower RH
                await self._heater_off(ctx, "vpd_low: temp above target -> heater_off")
                await self._reduce_humidity(ctx, "vpd_low: temp high -> reduce_humidity")
                ctx.data["debug_dehumidifier_reason"] = "vpd_low: temp high -> reduce_humidity (dehumidifier or exhaust)"
                await self._humidifier_off(ctx)
                ctx.data["debug_humidifier_reason"] = "vpd_low: temp high -> humidifier_off"
            else:
                # Temp at target — humidity is the issue, use dehumidifier
                await self._heater_off(ctx, "vpd_low: temp ok -> heater_off")
                await self._reduce_humidity(ctx, "vpd_low: temp ok -> reduce_humidity")
                ctx.data["debug_dehumidifier_reason"] = "vpd_low: temp ok -> reduce_humidity (dehumidifier or exhaust)"
                await self._humidifier_off(ctx)
                ctx.data["debug_humidifier_reason"] = "vpd_low: -> humidifier_off"

        elif ctx.vpd > high:
            # VPD too high — air is too dry and/or too warm.
            # Priority: reduce temperature toward target using exhaust.
            # Secondary: use humidifier if temp is already at/below target.
            if ctx.avg_temp > (target_temp + temp_db):
                # Temp above target — exhaust to cool
                await self._heater_off(ctx, "vpd_high: temp above target -> heater_off")
                await self._exhaust_on_if_off(ctx, "vpd_high: temp above target -> exhaust_on")
                await self._humidifier_off(ctx)
                ctx.data["debug_humidifier_reason"] = "vpd_high: cooling -> humidifier_off"
                await self._dehumidifier_off(ctx)
                ctx.data["debug_dehumidifier_reason"] = "vpd_high: cooling -> dehumidifier_off"
            elif ctx.avg_temp < (target_temp - temp_db):
                # Temp below target — humidifier to raise RH (raises VPD)
                await self._heater_off(ctx, "vpd_high: temp below target -> heater_off")
                await self._exhaust_off_if_on(ctx, "vpd_high: temp below target -> exhaust_off")
                await self._humidifier_on(ctx)
                ctx.data["debug_humidifier_reason"] = "vpd_high: temp low -> humidifier_on"
                await self._dehumidifier_off(ctx)
                ctx.data["debug_dehumidifier_reason"] = "vpd_high: temp low -> dehumidifier_off"
            else:
                # Temp at target — humidity is the issue, use humidifier
                await self._heater_off(ctx, "vpd_high: temp ok -> heater_off")
                await self._exhaust_off_if_on(ctx, "vpd_high: temp ok -> exhaust_off")
                await self._humidifier_on(ctx)
                ctx.data["debug_humidifier_reason"] = "vpd_high: temp ok -> humidifier_on"
                await self._dehumidifier_off(ctx)
                ctx.data["debug_dehumidifier_reason"] = "vpd_high: -> dehumidifier_off"

        else:
            # VPD in band — fine-tune temp and RH toward their targets
            ctx.data["debug_humidifier_reason"]   = "vpd_inband"
            ctx.data["debug_dehumidifier_reason"] = "vpd_inband"
            await self._heater_off(ctx, "vpd_inband -> heater_off")
            await self._exhaust_off_if_on(ctx, "vpd_inband -> exhaust_off")
            # Nudge RH toward target within deadband
            if ctx.avg_rh < (target_rh - rh_db):
                await self._humidifier_on(ctx)
                await self._dehumidifier_off(ctx)
                ctx.data["debug_humidifier_reason"]   = "vpd_inband: rh below target -> humidifier_on"
                ctx.data["debug_dehumidifier_reason"] = "vpd_inband: rh below target -> dehumidifier_off"
            elif ctx.avg_rh > (target_rh + rh_db):
                await self._reduce_humidity(ctx, "vpd_inband: rh above target -> reduce_humidity")
                await self._humidifier_off(ctx)
                ctx.data["debug_humidifier_reason"]   = "vpd_inband: rh above target -> humidifier_off"
                ctx.data["debug_dehumidifier_reason"] = "vpd_inband: rh above target -> reduce_humidity (dehumidifier or exhaust)"
            else:
                await self._humidifier_off(ctx)
                await self._dehumidifier_off(ctx)

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
            if self._exhaust_safety_blocks_off(ctx):
                ctx.data["debug_exhaust_reason"] = f"{reason} [SAFETY: blocked_off]"
                return
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

    async def _reduce_humidity(self, ctx: _Ctx, reason: str = "auto") -> None:
        """Reduce humidity: use dehumidifier if configured, otherwise exhaust fan."""
        if ctx.dehumidifier_eid:
            await self._dehumidifier_on(ctx, reason)
        else:
            await self._exhaust_on_if_off(ctx, f"{reason} [fallback: exhaust]")

    async def _stop_reducing_humidity(self, ctx: _Ctx, reason: str = "auto") -> None:
        """Stop active humidity reduction — mirrors _reduce_humidity."""
        if ctx.dehumidifier_eid:
            await self._dehumidifier_off(ctx, reason)
        else:
            await self._exhaust_off_if_on(ctx, f"{reason} [fallback: exhaust]")

    async def _circ_on(self, ctx: _Ctx, reason: str = "auto") -> None:
        if not ctx.circ_on and ctx.circ_eid:
            await self._async_switch(ctx.circ_eid, True)
            self._record_action(f"Circulation ON · {reason}")
            ctx.circ_on = True

    async def _circ_off(self, ctx: _Ctx, reason: str = "auto") -> None:
        if ctx.circ_on and ctx.circ_eid:
            await self._async_switch(ctx.circ_eid, False)
            self._record_action(f"Circulation OFF · {reason}")
            ctx.circ_on = False

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
        # Handled fully in _apply_forced_modes (On/Off overrides) and the
        # Auto block that follows ctx construction below.

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
                # Day On / Night On: when controller is disabled, treat as Auto
                # (no auto logic runs when disabled, so just skip these modes)
                if label == "Exhaust" and mode in ("Day On", "Night On"):
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
            circ_eid           = circ_eid,
            heater_on          = heater_on_actual,
            exhaust_on         = exhaust_on,
            humidifier_on      = humidifier_on,
            dehumidifier_on    = dehumidifier_on,
            circ_on            = self._switch_is_on(circ_eid) is True,
            exhaust_safety_on  = bool(data.get("exhaust_safety_override")),
            exhaust_safety_max_temp = float(data.get("exhaust_safety_max_temp_c", 30.0)),
            exhaust_safety_max_rh   = float(data.get("exhaust_safety_max_rh",     75.0)),
            heater_max_run_s   = float(data.get("heater_max_run_s", 0.0) or 0.0),
            night_mode         = data.get("night_mode", "Dew Protection"),
            night_vpd_target   = float(data.get("night_vpd_target_kpa", 1.00)),
            night_target_temp  = float(data.get("night_target_temp_c",  20.0)),
            night_target_rh    = float(data.get("night_target_rh",      55.0)),
            temp_ramp_rate     = float(data.get("temp_ramp_rate_c_per_min", 1.0)),
            day_mode           = data.get("day_mode", "VPD Chase"),
            mpc_horizon        = int(data.get("mpc_horizon_steps", 18)),
            mpc_temp_amb       = float(data.get("mpc_temp_amb",    20.0)),
            mpc_rh_amb         = float(data.get("mpc_rh_amb",      55.0)),
            mpc_a_heater       = float(data.get("mpc_a_heater",     0.423)),
            mpc_a_exhaust      = float(data.get("mpc_a_exhaust",   -0.082)),
            mpc_a_passive      = float(data.get("mpc_a_passive",    0.008)),
            mpc_a_bias         = float(data.get("mpc_a_bias",       0.057)),
            mpc_b_exhaust      = float(data.get("mpc_b_exhaust",   -1.196)),
            mpc_b_passive      = float(data.get("mpc_b_passive",    0.006)),
            mpc_b_bias         = float(data.get("mpc_b_bias",       0.556)),
            mpc_w_vpd          = float(data.get("mpc_w_vpd",        5.0)),
            mpc_w_temp         = float(data.get("mpc_w_temp",       2.0)),
            mpc_w_rh           = float(data.get("mpc_w_rh",         1.0)),
            mpc_w_switch       = float(data.get("mpc_w_switch",     0.5)),
        )

        # --- Temperature ramp ---
        # Slide the effective target temperatures toward their actual values at
        # no more than temp_ramp_rate °C/min.  This prevents abrupt jumps at the
        # day/night boundary and acts as a global protection against rapid
        # temperature changes at any time.
        ramp_rate = ctx.temp_ramp_rate

        # Detect day/night transition — reset ramp tracking to actual temp on
        # first poll and on each direction change to avoid a stale ramp base.
        if self.control.last_is_day != ctx.is_day:
            self.control.last_is_day = ctx.is_day
            self.control.ramped_target_temp_c = ctx.avg_temp  # start ramp from current temp

        # Determine the actual temperature target for this period
        actual_target_temp = float(data.get("target_temp_c", 25.0)) if ctx.is_day else ctx.night_target_temp

        # Slide effective target toward actual target at ramp rate
        if self.control.ramped_target_temp_c is None:
            self.control.ramped_target_temp_c = actual_target_temp
        self.control.ramped_target_temp_c = self._apply_temp_ramp(
            self.control.ramped_target_temp_c, actual_target_temp, ramp_rate
        )

        # Update ctx with ramped values so all sub-methods use them
        if ctx.is_day:
            data["target_temp_c"] = round(self.control.ramped_target_temp_c, 2)
        else:
            ctx.night_target_temp = round(self.control.ramped_target_temp_c, 2)
        data["debug_ramped_target_temp_c"] = round(self.control.ramped_target_temp_c, 2)

        # Apply forced On/Off overrides (handles On/Off modes for all devices
        # including circulation; sets ctx.circ_eid = None when override active)
        ctx = await self._apply_forced_modes(ctx)

        # --- Circulation Auto ---
        # If circ_eid is still set (i.e. mode is Auto), keep circulation running
        # whenever the controller is enabled and not in drying mode. Continuous
        # airflow is beneficial day and night for temperature equalisation,
        # boundary-layer disruption, and mould prevention.
        if ctx.circ_eid:
            if not enabled:
                ctx.data["debug_circulation_reason"] = "auto:off (controller disabled)"
                await self._circ_off(ctx, "auto: controller disabled")
            elif ctx.drying:
                ctx.data["debug_circulation_reason"] = "auto:off (drying)"
                await self._circ_off(ctx, "auto: drying mode")
            else:
                ctx.data["debug_circulation_reason"] = "auto:on (day/night)"
                await self._circ_on(ctx, "auto: controller enabled")

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
            # Safety: if sensors just became unavailable and the heater is on,
            # turn it off immediately. Leaving it running with no sensor feedback
            # is a fire/heat risk — it's far safer to turn it off and let the
            # user or the controller restart it once sensors recover.
            if heater_eid and heater_on_actual:
                await self._async_switch(heater_eid, False, blocking=True)
                self.control.last_heater_change = now
                self.control.heater_on_since = None
                self._record_action("Heater OFF · sensors unavailable safety shutoff")
                _LOGGER.warning(
                    "%s: heater turned off — sensors unavailable (safety shutoff)",
                    self.entry.title,
                )
            return data

        # Heater safety before anything else
        if await self._apply_heater_safety(ctx):
            return data

        data["debug_exhaust_policy"] = "normal"

        if drying:
            await self._apply_drying_mode(ctx)
        elif not is_day:
            if ctx.night_mode in (NIGHT_MODE_VPD, NIGHT_MODE_VPD_NO_HEATER):
                # Hard limits take priority over night VPD chase, same as day mode.
                # Without this check, a breach of max RH or max temp at night
                # would be ignored — VPD chase would continue trying to chase
                # its target regardless of safety limits being exceeded.
                hard_limit_active = await self._apply_day_hard_limits(ctx)
                if not hard_limit_active:
                    await self._apply_night_vpd_chase(ctx)
            else:
                await self._apply_night_mode(ctx)
        else:
            hard_limit_active = await self._apply_day_hard_limits(ctx)
            if not hard_limit_active:
                if ctx.day_mode == DAY_MODE_MPC:
                    await self._apply_mpc_day(ctx)
                elif ctx.day_mode == DAY_MODE_LIMITS:
                    ctx.data["control_mode"] = "limits_only"
                elif data.get("vpd_chase_enabled", True):
                    # Default / VPD Chase mode
                    await self._apply_vpd_chase(ctx)
                else:
                    ctx.data["control_mode"] = "limits_only"

        return data

    # ------------------------------------------------------------------ #
    #  VPD target stage-reset                                             #
    # ------------------------------------------------------------------ #

    async def _reset_stage_targets(self, stage: str) -> None:
        """Reset VPD target, temperature target, and RH target to stage defaults."""
        from homeassistant.helpers.entity_component import EntityComponent
        component: EntityComponent | None = self.hass.data.get("entity_components", {}).get("number")
        if component is None:
            return

        targets = {
            f"{self.entry.entry_id}_vpd_target_kpa":     STAGE_TARGET_VPD_KPA.get(stage, 1.00),
            f"{self.entry.entry_id}_target_temp_c":      STAGE_TARGET_TEMP_C.get(stage, 25.0),
            f"{self.entry.entry_id}_target_rh":          STAGE_TARGET_RH.get(stage, 55.0),
            f"{self.entry.entry_id}_night_vpd_target_kpa": STAGE_NIGHT_TARGET_VPD_KPA.get(stage, 1.00),
            f"{self.entry.entry_id}_night_target_temp_c":  STAGE_NIGHT_TARGET_TEMP_C.get(stage, 20.0),
            f"{self.entry.entry_id}_night_target_rh":      STAGE_NIGHT_TARGET_RH.get(stage, 55.0),
        }

        for entity in component.entities:
            uid = getattr(entity, "unique_id", None)
            if uid in targets and hasattr(entity, "async_set_to_stage_default"):
                await entity.async_set_to_stage_default(stage)
                _LOGGER.debug("Stage target reset for %s → stage: %s", uid, stage)

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
            "vpd_target_kpa":       self._num(_eid("vpd_target_kpa"),       1.00),
            "target_temp_c":        self._num(_eid("target_temp_c"),        25.0),
            "target_rh":            self._num(_eid("target_rh"),            55.0),
            "night_vpd_target_kpa": self._num(_eid("night_vpd_target_kpa"), 1.00),
            "night_target_temp_c":  self._num(_eid("night_target_temp_c"),  20.0),
            "night_target_rh":      self._num(_eid("night_target_rh"),      55.0),
            "temp_ramp_rate_c_per_min": self._num(_eid("temp_ramp_rate_c_per_min"), 1.0),
            "vpd_deadband_kpa":   self._num(_eid("vpd_deadband_kpa"),   0.07),
            "vpd_chase_enabled":  (self._get_entity_state(_eid("vpd_chase_enabled", "switch")) != "off"),
            "night_mode":         self._get_entity_state(_eid(CONF_NIGHT_MODE, "select")) or "Dew Protection",
            "day_mode":           self._get_entity_state(_eid(CONF_DAY_MODE, "select")) or "VPD Chase",
            # MPC parameters
            "mpc_horizon_steps":  int(self._num(_eid("mpc_horizon_steps"), 18)),
            "mpc_temp_amb":       self._num(_eid("mpc_temp_amb"),   20.0),
            "mpc_rh_amb":         self._num(_eid("mpc_rh_amb"),     55.0),
            "mpc_a_heater":       self._num(_eid("mpc_a_heater"),    0.423),
            "mpc_a_exhaust":      self._num(_eid("mpc_a_exhaust"),  -0.082),
            "mpc_a_passive":      self._num(_eid("mpc_a_passive"),   0.008),
            "mpc_a_bias":         self._num(_eid("mpc_a_bias"),      0.057),
            "mpc_b_exhaust":      self._num(_eid("mpc_b_exhaust"),  -1.196),
            "mpc_b_passive":      self._num(_eid("mpc_b_passive"),   0.006),
            "mpc_b_bias":         self._num(_eid("mpc_b_bias"),      0.556),
            "mpc_w_vpd":          self._num(_eid("mpc_w_vpd"),       5.0),
            "mpc_w_temp":         self._num(_eid("mpc_w_temp"),      2.0),
            "mpc_w_rh":           self._num(_eid("mpc_w_rh"),        1.0),
            "mpc_w_switch":       self._num(_eid("mpc_w_switch"),    0.5),
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
            "debug_target_temp_c":    None,
            "debug_target_rh":        None,
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
            "debug_ramped_target_temp_c": None,
            "debug_mpc_horizon":    0,
            "debug_mpc_score":      None,
            "debug_mpc_pred_temp":  None,
            "debug_mpc_pred_rh":    None,
            "debug_mpc_pred_vpd":   None,
            "debug_mpc_plan":       "n/a",
        }

        # --- Target conflict detection ---
        # Compute the VPD that would result from target_temp + target_rh
        # using the same leaf offset the controller uses for live VPD.
        # If this implied VPD deviates from target_vpd by more than a
        # threshold, the targets are inconsistent and the user should be warned.
        t_temp = float(data.get("target_temp_c", 25.0))
        t_rh   = float(data.get("target_rh",     55.0))
        t_vpd  = float(data.get("vpd_target_kpa", 1.00))
        t_leaf = t_temp + float(data.get("leaf_temp_offset_c", -1.5))
        implied_vpd = round(vpd_leaf_kpa(t_temp, t_rh, t_leaf), 3)
        conflict_pct = round(((implied_vpd - t_vpd) / t_vpd) * 100.0, 1) if t_vpd > 0 else 0.0
        # Implied RH needed at target_temp to actually hit target_vpd
        # VPD_leaf = SVP(leaf) - RH/100 * SVP(air)  →  RH = (SVP(leaf) - target_vpd) / SVP(air) * 100
        svp_air  = sat_vapor_pressure_kpa(t_temp)
        svp_leaf = sat_vapor_pressure_kpa(t_leaf)
        implied_rh = round(max(0.0, min(100.0, (svp_leaf - t_vpd) / svp_air * 100.0)), 1) if svp_air > 0 else t_rh
        data["target_vpd_implied"]   = implied_vpd
        data["target_conflict_pct"]  = conflict_pct
        data["target_implied_rh"]    = implied_rh

        data = await self._apply_control(data)

        # Stage-change detection: reset VPD target to stage default when stage changes
        current_stage = data.get("stage", DEFAULT_STAGE)
        if current_stage != self.control.last_stage:
            self.control.last_stage = current_stage
            await self._reset_stage_targets(current_stage)

        return data
