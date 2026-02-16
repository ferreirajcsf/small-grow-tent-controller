from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS, STAGE_TARGET_VPD_KPA
from .coordinator import GrowTentCoordinator

SERVICE_REFRESH = "refresh"
SERVICE_SET_STAGE = "set_stage"
SERVICE_SET_ENABLED = "set_enabled"


def _service_coordinators(hass: HomeAssistant, call) -> list[GrowTentCoordinator]:
    """Resolve coordinators targeted by a service call.

    Supports target.device_id / target.entity_id / target.area_id.
    If no explicit targets are provided, returns all coordinators.
    """
    target = getattr(call, "target", None)
    device_ids = list(getattr(target, "device_ids", []) or [])
    entity_ids = list(getattr(target, "entity_ids", []) or [])
    area_ids = list(getattr(target, "area_ids", []) or [])

    coordinators: dict[str, GrowTentCoordinator] = {}

    # 1) device targets (preferred for multi-instance)
    if device_ids:
        dev_reg = dr.async_get(hass)
        for device_id in device_ids:
            device = dev_reg.async_get(device_id)
            if not device:
                continue
            for ident_domain, ident in device.identifiers:
                if ident_domain == DOMAIN and ident in hass.data.get(DOMAIN, {}):
                    c = hass.data[DOMAIN].get(ident)
                    if c is not None:
                        coordinators[ident] = c


    # 1b) area targets -> devices in those areas
    if area_ids:
        dev_reg = dr.async_get(hass)
        for device in dev_reg.devices.values():
            if device.area_id and device.area_id in area_ids:
                for ident_domain, ident in device.identifiers:
                    if ident_domain == DOMAIN and ident in hass.data.get(DOMAIN, {}):
                        c = hass.data[DOMAIN].get(ident)
                        if c is not None:
                            coordinators[ident] = c

    # 2) entity targets
    if entity_ids:
        ent_reg = er.async_get(hass)
        for entity_id in entity_ids:
            ent = ent_reg.async_get(entity_id)
            if not ent or not ent.config_entry_id:
                continue
            c = hass.data.get(DOMAIN, {}).get(ent.config_entry_id)
            if c is not None:
                coordinators[ent.config_entry_id] = c

    # 3) no explicit target -> all instances
    if not coordinators and not device_ids and not entity_ids and not area_ids:
        for entry_id, c in hass.data.get(DOMAIN, {}).items():
            if isinstance(c, GrowTentCoordinator):
                coordinators[entry_id] = c

    return list(coordinators.values())


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once."""
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get("services_registered"):
        return

    async def _handle_refresh(call):
        for c in _service_coordinators(hass, call):
            await c.async_request_refresh()

    async def _handle_set_stage(call):
        stage = call.data.get("stage")
        if stage not in STAGE_TARGET_VPD_KPA:
            raise ServiceValidationError(
                f"Invalid stage '{stage}'. Valid: {', '.join(STAGE_TARGET_VPD_KPA.keys())}"
            )
        for c in _service_coordinators(hass, call):
            stage_eid = c._entity_id("select", "stage")
            await hass.services.async_call(
                "select",
                "select_option",
                {ATTR_ENTITY_ID: stage_eid, "option": stage},
                blocking=False,
            )

    async def _handle_set_enabled(call):
        enabled = call.data.get("enabled")
        if enabled is None:
            raise ServiceValidationError("Missing required field: enabled")
        service = "turn_on" if bool(enabled) else "turn_off"
        for c in _service_coordinators(hass, call):
            controller_eid = c._entity_id("switch", "controller")
            await hass.services.async_call(
                "switch",
                service,
                {ATTR_ENTITY_ID: controller_eid},
                blocking=False,
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        _handle_refresh,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STAGE,
        _handle_set_stage,
        schema=vol.Schema({vol.Required("stage"): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ENABLED,
        _handle_set_enabled,
        schema=vol.Schema({vol.Required("enabled"): cv.boolean}),
    )

    hass.data[DOMAIN]["services_registered"] = True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_services(hass)

    coordinator = GrowTentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
