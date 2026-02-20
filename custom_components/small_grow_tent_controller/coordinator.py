from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Any

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
)

_LOGGER = logging.getLogger(__name__)

# Stage-specific night behavior configuration
# exhaust_mode: "on" | "auto"
# dew_margin_add_c: extra °C added to the dew-point margin during lights-off
STAGE_NIGHT_PROFILE: dict[str, dict[str, Any]] = {
    "Seedling": {"exhaust_mode": "auto", "dew_margin_add_c": 0.0},
    "Vegetative": {"exhaust_mode": "on", "dew_margin_add_c": 0.0},
    "Early Flower": {"exhaust_mode": "on", "dew_margin_add_c": 0.0},
    "Mid Flower": {"exhaust_mode": "on", "dew_margin_add_c": 0.0},
    "Late Flower": {"exhaust_mode": "on", "dew_margin_add_c": 0.0},
    "Drying": {"exhaust_mode": "on", "dew_margin_add_c": 1.0},
}

# Exhaust forced ON during these stages (day + night)
ALWAYS_EXHAUST_ON_STAGES: set[str] = {"Mid Flower", "Late Flower"}


@dataclass
class ControlState:
    last_heater_change: datetime | None = None
    last_exhaust_change: datetime | None = None
    last_light_change: datetime | None = None
    last_humidifier_change: datetime | None = None
    last_dehumidifier_change: datetime | None = None

    # Heater pulse control
    heater_pulse_until: datetime | None = None
    heater_cooldown_until: datetime | None = None

    # Heater safety: max continuous run time
    heater_on_since: datetime | None = None
    heater_max_lockout_until: datetime | None = None


class GrowTentCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.control = ControlState()

        super().__init__(
            hass,
            _LOGGER,  # IMPORTANT: must not be None
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=10),
        )

    # ---------- helpers ----------
    def _get_state_float(self, entity_id: str) -> float | None:
        st = self.hass.states.get(entity_id)
        if st is None:
            return None
        return safe_float(st.state)

    def _get_option(self, key: str) -> Any:
        # Prefer options (editable) over data (initial).
        # IMPORTANT: options can legitimately be False/0/"" — don't treat those as "missing".
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key)

    def _now(self) -> datetime:
        return dt_util.now()

    def _is_time_between(self, now_t: time, start: time, end: time) -> bool:
        # Handles normal and overnight schedules
        if start <= end:
            return start <= now_t < end
        return now_t >= start or now_t < end

    async def _async_switch(self, entity_id: str, turn_on: bool) -> None:
        # All controlled devices are switches
        service = "turn_on" if turn_on else "turn_off"
        await self.hass.services.async_call(
            "switch",
            service,
            {"entity_id": entity_id},
            blocking=False,
        )

    def _entity_id(self, domain: str, key: str) -> str:
        """Resolve current entity_id from unique_id, even if user renamed it."""
        registry = er.async_get(self.hass)
        unique_id = f"{self.entry.entry_id}_{key}"
        eid = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        return eid or f"{domain}.{self.entry.entry_id}_{key}"

    def _switch_is_on(self, entity_id: str | None) -> bool | None:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if st is None:
            return None
        return st.state == "on"

    def _can_toggle(self, last_change: datetime | None, hold_seconds: float) -> bool:
        if last_change is None:
            return True
        return (self._now() - last_change).total_seconds() >= hold_seconds

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
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            ss = int(parts[2]) if len(parts) > 2 else 0
            return time(hh, mm, ss)
        except Exception:
            return default

    def _heater_pulse_plan(self, error_c: float) -> tuple[int, int]:
        """Return (on_seconds, off_seconds) for a simple heater pulse plan."""
        if error_c >= 1.5:
            return (9999, 0)  # effectively continuous
        if error_c >= 0.8:
            return (30, 30)
        if error_c >= 0.3:
            return (10, 50)
        return (0, 60)

    def _heater_allowed_on(self, now: datetime) -> bool:
        """Block heater ON while in max-run lockout window."""
        if self.control.heater_max_lockout_until and now < self.control.heater_max_lockout_until:
            return False
        return True

    # ---------- core control ----------
    async def _apply_control(self, data: dict[str, Any]) -> dict[str, Any]:
        enabled: bool = data.get("controller_enabled", True)
        stage: str = data.get("stage", DEFAULT_STAGE)
        drying: bool = stage == "Drying"

        min_temp: float = data.get("min_temp_c", 20.0)
        max_temp: float = data.get("max_temp_c", 30.0)
        min_rh: float = data.get("min_rh", 40.0)
        max_rh: float = data.get("max_rh", 70.0)

        light_on: time = data.get("light_on_time")
        light_off: time = data.get("light_off_time")

        if not isinstance(light_on, time):
            light_on = time(9, 0, 0)
        if not isinstance(light_off, time):
            light_off = time(21, 0, 0)

        dew_margin: float = data.get("dewpoint_margin_c", 1.0)

        heater_hold: float = data.get("heater_hold_s", 60.0)
        exhaust_hold: float = data.get("exhaust_hold_s", 45.0)
        humidifier_hold: float = data.get("humidifier_hold_s", exhaust_hold)
        dehumidifier_hold: float = data.get("dehumidifier_hold_s", exhaust_hold)

        # Controlled device entity ids (from config options)
        light_eid = self._get_option(CONF_LIGHT_SWITCH)
        circ_eid = self._get_option(CONF_CIRC_SWITCH)
        exhaust_eid = self._get_option(CONF_EXHAUST_SWITCH)
        heater_eid = self._get_option(CONF_HEATER_SWITCH)
        humidifier_eid = self._get_option(CONF_HUMIDIFIER_SWITCH)
        dehumidifier_eid = self._get_option(CONF_DEHUMIDIFIER_SWITCH)

        # Device enable flags (if disabled, treat entity as not configured)
        use_light = bool(self._get_option(CONF_USE_LIGHT) if self._get_option(CONF_USE_LIGHT) is not None else True)
        use_circ = bool(self._get_option(CONF_USE_CIRCULATION) if self._get_option(CONF_USE_CIRCULATION) is not None else True)
        use_exhaust = bool(self._get_option(CONF_USE_EXHAUST) if self._get_option(CONF_USE_EXHAUST) is not None else True)
        use_heater = bool(self._get_option(CONF_USE_HEATER) if self._get_option(CONF_USE_HEATER) is not None else True)
        use_humidifier = bool(self._get_option(CONF_USE_HUMIDIFIER) if self._get_option(CONF_USE_HUMIDIFIER) is not None else True)
        use_dehumidifier = bool(self._get_option(CONF_USE_DEHUMIDIFIER) if self._get_option(CONF_USE_DEHUMIDIFIER) is not None else True)

        if not use_light:
            light_eid = None
        if not use_circ:
            circ_eid = None
        if not use_exhaust:
            exhaust_eid = None
        if not use_heater:
            heater_eid = None
        if not use_humidifier:
            humidifier_eid = None
        if not use_dehumidifier:
            dehumidifier_eid = None

        now = self._now()
        now_t = dt_util.as_local(now).time()

        # Decide day/night by schedule
        is_day = self._is_time_between(now_t, light_on, light_off)

        # Drying policy: ignore schedule for lights (always OFF)
        if drying:
            is_day = False
            data["debug_light_window"] = (
                f"{light_on.strftime('%H:%M:%S')}–{light_off.strftime('%H:%M:%S')} (ignored: drying)"
            )
        else:
            data["debug_light_window"] = f"{light_on.strftime('%H:%M:%S')}–{light_off.strftime('%H:%M:%S')}"

        data["debug_is_day"] = is_day

        # --- Light decision reasoning ---
        cur_light_state = self._switch_is_on(light_eid)
        if light_eid is None:
            data["debug_light_reason"] = "light_entity_not_configured"
        elif cur_light_state is None:
            data["debug_light_reason"] = "light_state_unknown"
        elif drying:
            data["debug_light_reason"] = "drying -> force_off"
        elif is_day and not cur_light_state:
            data["debug_light_reason"] = "schedule_day_window -> turn_on"
        elif (not is_day) and cur_light_state:
            data["debug_light_reason"] = "schedule_night_window -> turn_off"
        else:
            data["debug_light_reason"] = "schedule_ok -> no_change"

        # FAILSAFE: light policy
        if light_eid and cur_light_state is not None:
            if drying:
                # Always force OFF, no matter what the schedule is.
                if cur_light_state and self._can_toggle(self.control.last_light_change, 10):
                    await self._async_switch(light_eid, False)
                    self.control.last_light_change = now
            else:
                # Normal behavior: light matches schedule.
                if (not is_day) and cur_light_state:
                    if self._can_toggle(self.control.last_light_change, 10):
                        await self._async_switch(light_eid, False)
                        self.control.last_light_change = now
                elif is_day and (not cur_light_state):
                    if self._can_toggle(self.control.last_light_change, 10):
                        await self._async_switch(light_eid, True)
                        self.control.last_light_change = now

        # Circulation fan always on when controller enabled
        if enabled and circ_eid:
            cur_circ = self._switch_is_on(circ_eid)
            if cur_circ is not None and (not cur_circ):
                await self._async_switch(circ_eid, True)

        if not enabled:
            data["control_mode"] = "disabled"
            return data

        avg_temp = data.get("avg_temp_c")
        avg_rh = data.get("avg_rh")
        dew = data.get("dew_point_c")
        vpd = data.get("vpd_kpa")

        if avg_temp is None or avg_rh is None or dew is None or vpd is None:
            data["control_mode"] = "waiting_for_sensors"
            return data

        # Current device states
        heater_on = self._switch_is_on(heater_eid) is True
        exhaust_on = self._switch_is_on(exhaust_eid) is True
        humidifier_on = self._switch_is_on(humidifier_eid) is True
        dehumidifier_on = self._switch_is_on(dehumidifier_eid) is True

        # ----------------------------
        # HEATER SAFETY: max continuous run time
        # - heater_max_run_s == 0 => disabled
        # - if exceeded => force OFF immediately + lockout for heater_hold_s
        # ----------------------------
        heater_max_run_s = float(data.get("heater_max_run_s", 0.0) or 0.0)
        data["debug_heater_max_run_s"] = heater_max_run_s
        data["debug_heater_lockout"] = (
            "active"
            if (self.control.heater_max_lockout_until and now < self.control.heater_max_lockout_until)
            else "inactive"
        )

        # Track on-since
        if heater_on:
            if self.control.heater_on_since is None:
                self.control.heater_on_since = now
        else:
            self.control.heater_on_since = None

        # Debug: how long it has been on
        if heater_on and self.control.heater_on_since:
            data["debug_heater_on_for_s"] = int((now - self.control.heater_on_since).total_seconds())
        else:
            data["debug_heater_on_for_s"] = 0

        # Enforce lockout: if active, heater must be OFF
        if self.control.heater_max_lockout_until and now < self.control.heater_max_lockout_until:
            if heater_on and heater_eid:
                await self._async_switch(heater_eid, False)  # safety override (ignore hold)
                self.control.last_heater_change = now
                self.control.heater_on_since = None
                heater_on = False
            # Don’t return here — the rest can still run (exhaust logic etc.), but heater ON is blocked by _heater_allowed_on()

        # Trip if exceeded
        if (
            heater_max_run_s > 0
            and heater_on
            and heater_eid
            and self.control.heater_on_since is not None
            and (now - self.control.heater_on_since).total_seconds() >= heater_max_run_s
        ):
            await self._async_switch(heater_eid, False)  # safety override (ignore hold)
            self.control.last_heater_change = now
            self.control.heater_on_since = None
            heater_on = False

            # Lockout prevents immediate re-on
            self.control.heater_max_lockout_until = now + timedelta(seconds=float(heater_hold))

            data["control_mode"] = "safety_trip:heater_max_run"
            data["debug_heater_reason"] = "max_run_time_exceeded -> forced_off"
            data["debug_heater_lockout"] = "active"
            return data

        # ----------------------------
        # DRYING MODE: hard limits only
        # - lights are forced off above
        # - ignore night mode dew protection
        # - ignore VPD chase
        # - enforce only min/max temp and min/max RH
        # ----------------------------
        if drying:
            hard_limit = None
            if avg_temp < min_temp:
                hard_limit = "temp_below_min"
            elif avg_temp > max_temp:
                hard_limit = "temp_above_max"
            elif avg_rh < min_rh:
                hard_limit = "rh_below_min"
            elif avg_rh > max_rh:
                hard_limit = "rh_above_max"

            data["control_mode"] = (
                "drying_hard_limits_only" if hard_limit is None else f"drying_hard_limit:{hard_limit}"
            )

            # Neutralize when in-band (no chasing)
            if hard_limit is None:
                if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                if exhaust_on and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now
                data["debug_heater_reason"] = "drying: in-band -> neutral"
                data["debug_exhaust_reason"] = "drying: in-band -> neutral"
                return data

            if hard_limit == "temp_below_min":
                if (
                    (not heater_on)
                    and heater_eid
                    and self._heater_allowed_on(now)
                    and self._can_toggle(self.control.last_heater_change, heater_hold)
                ):
                    await self._async_switch(heater_eid, True)
                    self.control.last_heater_change = now
                if exhaust_on and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now
                data["debug_heater_reason"] = "drying: temp_below_min -> heater_on"
                data["debug_exhaust_reason"] = "drying: temp_below_min -> exhaust_off"
                return data

            if hard_limit == "temp_above_max":
                if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                if (not exhaust_on) and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now
                data["debug_heater_reason"] = "drying: temp_above_max -> heater_off"
                data["debug_exhaust_reason"] = "drying: temp_above_max -> exhaust_on"
                return data

            if hard_limit == "rh_above_max":
                if (avg_temp > min_temp) and (not exhaust_on) and exhaust_eid and self._can_toggle(
                    self.control.last_exhaust_change, exhaust_hold
                ):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now
                if heater_on and heater_eid and (avg_temp >= min_temp) and self._can_toggle(
                    self.control.last_heater_change, heater_hold
                ):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                # Humidity devices
                if humidifier_on and humidifier_eid and self._can_toggle(self.control.last_humidifier_change, humidifier_hold):
                    await self._async_switch(humidifier_eid, False)
                    self.control.last_humidifier_change = now
                    humidifier_on = False
                if (not dehumidifier_on) and dehumidifier_eid and self._can_toggle(
                    self.control.last_dehumidifier_change, dehumidifier_hold
                ):
                    await self._async_switch(dehumidifier_eid, True)
                    self.control.last_dehumidifier_change = now
                    dehumidifier_on = True

                data["debug_heater_reason"] = "drying: rh_above_max -> heater_off"
                data["debug_exhaust_reason"] = "drying: rh_above_max -> exhaust_on"
                return data

            if hard_limit == "rh_below_min":
                if exhaust_on and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now
                if heater_on and heater_eid and (avg_temp > min_temp) and self._can_toggle(
                    self.control.last_heater_change, heater_hold
                ):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                # Humidity devices
                if dehumidifier_on and dehumidifier_eid and self._can_toggle(
                    self.control.last_dehumidifier_change, dehumidifier_hold
                ):
                    await self._async_switch(dehumidifier_eid, False)
                    self.control.last_dehumidifier_change = now
                    dehumidifier_on = False
                if (not humidifier_on) and humidifier_eid and self._can_toggle(
                    self.control.last_humidifier_change, humidifier_hold
                ):
                    await self._async_switch(humidifier_eid, True)
                    self.control.last_humidifier_change = now
                    humidifier_on = True

                data["debug_heater_reason"] = "drying: rh_below_min -> heater_off"
                data["debug_exhaust_reason"] = "drying: rh_below_min -> exhaust_off"
                return data

            # Should not reach here, but keep safe.
            return data

        # ----------------------------
        # NORMAL MODE (non-drying)
        # ----------------------------

        # Force exhaust ON for specific stages (day + night)
        force_exhaust_on = enabled and (stage in ALWAYS_EXHAUST_ON_STAGES)
        if force_exhaust_on:
            data["debug_exhaust_policy"] = "forced_on_stage"
            if (not exhaust_on) and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                await self._async_switch(exhaust_eid, True)
                self.control.last_exhaust_change = now
                _LOGGER.info("Exhaust ON: forced_on_stage (%s)", stage)
            exhaust_on = True
        else:
            data["debug_exhaust_policy"] = "normal"

        # ---------- NIGHT MODE ----------
        if not is_day:
            profile = STAGE_NIGHT_PROFILE.get(stage, {"exhaust_mode": "on", "dew_margin_add_c": 0.0})
            exhaust_mode = profile.get("exhaust_mode", "on")
            dew_margin_night = dew_margin + float(profile.get("dew_margin_add_c", 0.0))

            if force_exhaust_on:
                exhaust_mode = "on"

            data["control_mode"] = f"night_{exhaust_mode}_dewpoint_protect"

            # Humidity devices at night:
            # - humidifier is forced OFF to avoid adding moisture during dewpoint protection
            # - dehumidifier may run if RH is above max_rh
            if humidifier_on and humidifier_eid and self._can_toggle(self.control.last_humidifier_change, humidifier_hold):
                await self._async_switch(humidifier_eid, False)
                self.control.last_humidifier_change = now
                humidifier_on = False
                data["debug_humidifier_reason"] = "night: force_off"
            if (avg_rh > max_rh) and (not dehumidifier_on) and dehumidifier_eid and self._can_toggle(
                self.control.last_dehumidifier_change, dehumidifier_hold
            ):
                await self._async_switch(dehumidifier_eid, True)
                self.control.last_dehumidifier_change = now
                dehumidifier_on = True
                data["debug_dehumidifier_reason"] = "night: rh_above_max -> on"
            elif (avg_rh <= max_rh) and dehumidifier_on and dehumidifier_eid and self._can_toggle(
                self.control.last_dehumidifier_change, dehumidifier_hold
            ):
                await self._async_switch(dehumidifier_eid, False)
                self.control.last_dehumidifier_change = now
                dehumidifier_on = False
                data["debug_dehumidifier_reason"] = "night: rh_ok -> off"

            # Heater dewpoint protection with soft pulsing
            target_temp = dew + dew_margin_night
            target_temp = min(target_temp, max_temp)  # safety cap

            error = target_temp - avg_temp  # positive => below target
            on_s, off_s = self._heater_pulse_plan(error)

            data["debug_heater_target_c"] = round(target_temp, 2)
            data["debug_heater_error_c"] = round(error, 2)

            if on_s == 0:
                data["debug_heater_reason"] = "night: at/above dew target -> off"
                self.control.heater_pulse_until = None
                self.control.heater_cooldown_until = None

                if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                    _LOGGER.info(
                        "Heater OFF (night): at/above dew target. avg=%.2f target=%.2f",
                        avg_temp,
                        target_temp,
                    )
                    heater_on = False
            else:
                # cooldown window keeps heater off
                if self.control.heater_cooldown_until and now < self.control.heater_cooldown_until:
                    data["debug_heater_reason"] = "night: cooldown"
                    if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                        await self._async_switch(heater_eid, False)
                        self.control.last_heater_change = now
                        _LOGGER.info("Heater OFF (night): cooldown active.")
                        heater_on = False
                else:
                    data["debug_heater_reason"] = f"night: pulse plan on={on_s}s off={off_s}s"

                    # Start pulse if currently off
                    if not heater_on:
                        self.control.heater_pulse_until = now + timedelta(seconds=on_s)

                        if (
                            heater_eid
                            and self._heater_allowed_on(now)
                            and self._can_toggle(self.control.last_heater_change, heater_hold)
                        ):
                            await self._async_switch(heater_eid, True)
                            self.control.last_heater_change = now
                            _LOGGER.info(
                                "Heater ON (night): pulse start. avg=%.2f target=%.2f on=%ss off=%ss",
                                avg_temp,
                                target_temp,
                                on_s,
                                off_s,
                            )
                            heater_on = True
                    else:
                        # ensure pulse timer exists
                        if self.control.heater_pulse_until is None:
                            self.control.heater_pulse_until = now + timedelta(seconds=on_s)

                    # End pulse when time elapsed
                    if (
                        heater_on
                        and self.control.heater_pulse_until
                        and now >= self.control.heater_pulse_until
                        and heater_eid
                    ):
                        if self._can_toggle(self.control.last_heater_change, heater_hold):
                            await self._async_switch(heater_eid, False)
                            self.control.last_heater_change = now
                            heater_on = False
                            _LOGGER.info("Heater OFF (night): pulse end -> cooldown %ss", off_s)
                            self.control.heater_pulse_until = None
                            self.control.heater_cooldown_until = now + timedelta(seconds=off_s)

            # Exhaust behavior at night
            if exhaust_mode == "on":
                data["debug_exhaust_reason"] = "night: profile=on"
                if (not exhaust_on) and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now
                    _LOGGER.info("Exhaust ON (night): profile=on")
                    exhaust_on = True

            elif exhaust_mode == "auto":
                want_exhaust = (avg_rh > max_rh) or (avg_temp > max_temp)
                data["debug_exhaust_reason"] = f"night: auto want_exhaust={want_exhaust}"

                if (
                    want_exhaust
                    and (not exhaust_on)
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now
                    _LOGGER.info(
                        "Exhaust ON (night auto): avg_rh=%.1f max_rh=%.1f avg_temp=%.2f max_temp=%.2f",
                        avg_rh,
                        max_rh,
                        avg_temp,
                        max_temp,
                    )
                    exhaust_on = True
                elif (
                    (not want_exhaust)
                    and exhaust_on
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now
                    _LOGGER.info("Exhaust OFF (night auto): conditions cleared")
                    exhaust_on = False

            return data

        # ---------- DAY MODE ----------
        hard_limit = None
        if avg_temp < min_temp:
            hard_limit = "temp_below_min"
        elif avg_temp > max_temp:
            hard_limit = "temp_above_max"
        elif avg_rh < min_rh:
            hard_limit = "rh_below_min"
        elif avg_rh > max_rh:
            hard_limit = "rh_above_max"

        if hard_limit:
            data["control_mode"] = f"hard_limit:{hard_limit}"

            if hard_limit == "temp_below_min":
                if (
                    (not heater_on)
                    and heater_eid
                    and self._heater_allowed_on(now)
                    and self._can_toggle(self.control.last_heater_change, heater_hold)
                ):
                    await self._async_switch(heater_eid, True)
                    self.control.last_heater_change = now
                if (
                    (not force_exhaust_on)
                    and exhaust_on
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now

            elif hard_limit == "temp_above_max":
                if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                if (not exhaust_on) and exhaust_eid and self._can_toggle(self.control.last_exhaust_change, exhaust_hold):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now

            elif hard_limit == "rh_above_max":
                if (
                    (avg_temp > min_temp)
                    and (not exhaust_on)
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now
                if heater_on and heater_eid and (avg_temp >= min_temp) and self._can_toggle(
                    self.control.last_heater_change, heater_hold
                ):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                # Humidity devices
                if humidifier_on and humidifier_eid and self._can_toggle(
                    self.control.last_humidifier_change, humidifier_hold
                ):
                    await self._async_switch(humidifier_eid, False)
                    self.control.last_humidifier_change = now
                    humidifier_on = False
                if (not dehumidifier_on) and dehumidifier_eid and self._can_toggle(
                    self.control.last_dehumidifier_change, dehumidifier_hold
                ):
                    await self._async_switch(dehumidifier_eid, True)
                    self.control.last_dehumidifier_change = now
                    dehumidifier_on = True


            elif hard_limit == "rh_below_min":
                if (
                    (not force_exhaust_on)
                    and exhaust_on
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now
                if heater_on and heater_eid and (avg_temp > min_temp) and self._can_toggle(
                    self.control.last_heater_change, heater_hold
                ):
                    await self._async_switch(heater_eid, False)
                    self.control.last_heater_change = now
                # Humidity devices
                if dehumidifier_on and dehumidifier_eid and self._can_toggle(
                    self.control.last_dehumidifier_change, dehumidifier_hold
                ):
                    await self._async_switch(dehumidifier_eid, False)
                    self.control.last_dehumidifier_change = now
                    dehumidifier_on = False
                if (not humidifier_on) and humidifier_eid and self._can_toggle(
                    self.control.last_humidifier_change, humidifier_hold
                ):
                    await self._async_switch(humidifier_eid, True)
                    self.control.last_humidifier_change = now
                    humidifier_on = True


            return data

        # ---------- VPD chase ----------
        data["control_mode"] = "vpd_chase"
        target_vpd = STAGE_TARGET_VPD_KPA.get(stage, STAGE_TARGET_VPD_KPA[DEFAULT_STAGE])
        deadband = float(data.get("vpd_deadband_kpa", 0.07))

        low = target_vpd - deadband
        high = target_vpd + deadband

        if vpd < low:
            # Too humid (low VPD): dehumidify first (if available), otherwise fall back to heat/exhaust.
            if (not dehumidifier_on) and dehumidifier_eid and self._can_toggle(
                self.control.last_dehumidifier_change, dehumidifier_hold
            ):
                await self._async_switch(dehumidifier_eid, True)
                self.control.last_dehumidifier_change = now
                dehumidifier_on = True
                data["debug_dehumidifier_reason"] = "vpd_low -> on"

            # Never run humidifier while trying to raise VPD
            if humidifier_on and humidifier_eid and self._can_toggle(
                self.control.last_humidifier_change, humidifier_hold
            ):
                await self._async_switch(humidifier_eid, False)
                self.control.last_humidifier_change = now
                humidifier_on = False
                data["debug_humidifier_reason"] = "vpd_low -> off"

            # Existing strategy: heat if temp headroom, else exhaust if RH headroom
            if avg_temp < (max_temp - 0.2):
                if (
                    (not heater_on)
                    and heater_eid
                    and self._heater_allowed_on(now)
                    and self._can_toggle(self.control.last_heater_change, heater_hold)
                ):
                    await self._async_switch(heater_eid, True)
                    self.control.last_heater_change = now
                if (
                    (not force_exhaust_on)
                    and exhaust_on
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, False)
                    self.control.last_exhaust_change = now
            else:
                if (
                    (avg_rh > (min_rh + 1.0))
                    and (not exhaust_on)
                    and exhaust_eid
                    and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
                ):
                    await self._async_switch(exhaust_eid, True)
                    self.control.last_exhaust_change = now

        elif vpd > high:
            # Too dry (high VPD): humidify (if available) and stop drying forces.
            if dehumidifier_on and dehumidifier_eid and self._can_toggle(
                self.control.last_dehumidifier_change, dehumidifier_hold
            ):
                await self._async_switch(dehumidifier_eid, False)
                self.control.last_dehumidifier_change = now
                dehumidifier_on = False

            if (not humidifier_on) and humidifier_eid and self._can_toggle(
                self.control.last_humidifier_change, humidifier_hold
            ):
                await self._async_switch(humidifier_eid, True)
                self.control.last_humidifier_change = now
                humidifier_on = True
                data["debug_humidifier_reason"] = "vpd_high -> on"

            if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                await self._async_switch(heater_eid, False)
                self.control.last_heater_change = now
            if (
                (not force_exhaust_on)
                and exhaust_on
                and exhaust_eid
                and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
            ):
                await self._async_switch(exhaust_eid, False)
                self.control.last_exhaust_change = now

        else:
            # In band: stable (neutralize).
            if humidifier_on and humidifier_eid and self._can_toggle(
                self.control.last_humidifier_change, humidifier_hold
            ):
                await self._async_switch(humidifier_eid, False)
                self.control.last_humidifier_change = now
                humidifier_on = False
            if dehumidifier_on and dehumidifier_eid and self._can_toggle(
                self.control.last_dehumidifier_change, dehumidifier_hold
            ):
                await self._async_switch(dehumidifier_eid, False)
                self.control.last_dehumidifier_change = now
                dehumidifier_on = False

            if heater_on and heater_eid and self._can_toggle(self.control.last_heater_change, heater_hold):
                await self._async_switch(heater_eid, False)
                self.control.last_heater_change = now
            if (
                (not force_exhaust_on)
                and exhaust_on
                and exhaust_eid
                and self._can_toggle(self.control.last_exhaust_change, exhaust_hold)
            ):
                await self._async_switch(exhaust_eid, False)
                self.control.last_exhaust_change = now

        return data

    async def _async_update_data(self) -> dict[str, Any]:
        # Raw sensors
        canopy_t = self._get_state_float(self._get_option(CONF_CANOPY_TEMP))
        top_t = self._get_state_float(self._get_option(CONF_TOP_TEMP))
        canopy_rh = self._get_state_float(self._get_option(CONF_CANOPY_RH))
        top_rh = self._get_state_float(self._get_option(CONF_TOP_RH))

        avg_t = avg([canopy_t, top_t])
        avg_r = avg([canopy_rh, top_rh])

        # Leaf offset (user-adjustable Number entity)
        leaf_off_eid = self._entity_id("number", "leaf_temp_offset_c")
        leaf_offset_c = self._num(leaf_off_eid, 0.0)

        vpd = dew = None
        leaf_temp_c = None

        if avg_t is not None and avg_r is not None:
            leaf_temp_c = avg_t + float(leaf_offset_c)
            vpd = vpd_leaf_kpa(avg_t, avg_r, leaf_temp_c)
            dew = dew_point_c(avg_t, avg_r)

        # Entities created by this integration (resolve via unique_id)
        controller_eid = self._entity_id("switch", "controller")
        stage_eid = self._entity_id("select", "stage")

        min_temp_eid = self._entity_id("number", "min_temp_c")
        max_temp_eid = self._entity_id("number", "max_temp_c")
        min_rh_eid = self._entity_id("number", "min_rh")
        max_rh_eid = self._entity_id("number", "max_rh")
        deadband_eid = self._entity_id("number", "vpd_deadband_kpa")
        dew_margin_eid = self._entity_id("number", "dewpoint_margin_c")
        heater_hold_eid = self._entity_id("number", "heater_hold_s")
        exhaust_hold_eid = self._entity_id("number", "exhaust_hold_s")
        humidifier_hold_eid = self._entity_id("number", "humidifier_hold_s")
        dehumidifier_hold_eid = self._entity_id("number", "dehumidifier_hold_s")

        # NEW: heater max run time number
        heater_max_run_eid = self._entity_id("number", "heater_max_run_s")

        light_on_eid = self._entity_id("time", "light_on")
        light_off_eid = self._entity_id("time", "light_off")

        enabled_state = self._get_entity_state(controller_eid)
        controller_enabled = (enabled_state == "on") if enabled_state is not None else True

        stage_state = self._get_entity_state(stage_eid)
        stage = stage_state if stage_state in STAGE_TARGET_VPD_KPA else DEFAULT_STAGE

        light_on_s = self._get_entity_state(light_on_eid)
        light_off_s = self._get_entity_state(light_off_eid)

        # Debug: controller local time
        now_local = dt_util.as_local(self._now())
        debug_local_time = now_local.strftime("%Y-%m-%d %H:%M:%S")
        debug_local_tod = now_local.strftime("%H:%M:%S")

        data: dict[str, Any] = {
            "canopy_temp_c": canopy_t,
            "top_temp_c": top_t,
            "canopy_rh": canopy_rh,
            "top_rh": top_rh,
            "avg_temp_c": avg_t,
            "avg_rh": avg_r,
            "vpd_kpa": vpd,
            "dew_point_c": dew,
            "controller_enabled": controller_enabled,
            "stage": stage,
            "min_temp_c": self._num(min_temp_eid, 20.0),
            "max_temp_c": self._num(max_temp_eid, 30.0),
            "min_rh": self._num(min_rh_eid, 40.0),
            "max_rh": self._num(max_rh_eid, 70.0),
            "vpd_deadband_kpa": self._num(deadband_eid, 0.07),
            "dewpoint_margin_c": self._num(dew_margin_eid, 1.0),
            "heater_hold_s": self._num(heater_hold_eid, 60.0),
            "exhaust_hold_s": self._num(exhaust_hold_eid, 45.0),
            "humidifier_hold_s": self._num(humidifier_hold_eid, 45.0),
            "dehumidifier_hold_s": self._num(dehumidifier_hold_eid, 45.0),

            # NEW: user adjustable max run time (0 disables)
            "heater_max_run_s": self._num(heater_max_run_eid, 0.0),

            "light_on_time": self._parse_time(light_on_s, time(9, 0, 0)),
            "light_off_time": self._parse_time(light_off_s, time(21, 0, 0)),
            "control_mode": "init",
            # Leaf model (optional exposure; safe even if you don't create sensors for these)
            "leaf_temp_offset_c": float(leaf_offset_c),
            "leaf_temp_c": leaf_temp_c,
            # Debug: controller local time
            "debug_local_time": debug_local_time,
            "debug_local_tod": debug_local_tod,
            # Defaults (so entities always have a state on every refresh)
            "debug_light_reason": "n/a",
            "debug_exhaust_policy": "n/a",
            "debug_exhaust_reason": "n/a",
            "debug_heater_reason": "n/a",
            # Numeric defaults (must be numeric or None)
            "debug_heater_target_c": None,
            "debug_heater_error_c": None,

            # NEW debug fields for max-run feature
            "debug_heater_on_for_s": 0,
            "debug_heater_max_run_s": 0.0,
            "debug_heater_lockout": "inactive",
        }

        # Control actions (may add debug_* fields and switch actions)
        data = await self._apply_control(data)
        return data
