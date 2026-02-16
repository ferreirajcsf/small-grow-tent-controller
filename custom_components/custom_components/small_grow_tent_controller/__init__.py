from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS, STAGE_TARGET_VPD_KPA
from .coordinator import GrowTentCoordinator

SERVICE_REFRESH = "refresh"
SERVICE_SET_STAGE = "set_stage"
SERVICE_SET_ENABLED = "set_enabled"

_DATA_COORDINATORS = "coordinators"
_DATA_SERVICES_REGISTERED = "services_registered"


def _domain_data(hass: HomeAssistant) -> dict:
    """Return the domain data dict, creating the default structure if needed."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(_DATA_COORDINATORS, {})
    hass.data[DOMAIN].setdefault(_DATA_SERVICES_REGISTERED, False)
    return hass.data[DOMAIN]


def _service_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[GrowTentCoordinator]:
    """Resolve coordinators targeted by a service call.

    Supports target.device_id / target.entity_id / target.area_id.
    If no explicit targets are provided, returns all coordinators.
    """
    data = _domain_data(hass)
    all_coords: dict[str, GrowTentCoordinator] = data[_DATA_COORDINATORS]

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
                if ident_domain == DOMAIN and ident in all_coords:
                    coordinators[ident] = all_coords[ident]

    # 1b) area targets -> devices in those areas
    if area_ids:
        dev_reg = dr.async_get(hass)
        for device in dev_reg.devices.values():
            if device.area_id and device.area_id in area_ids:
                for ident_domain, ident in device.identifiers:
                    if ident_domain == DOMAIN and ident in all_coords:
                        coordinators[ident] = all_coords[ident]

    # 2) entity targets
    if entity_ids:
        ent_reg = er.async_get(hass)
        for entity_id in entity_ids:
            ent = ent_reg.async_get(entity_id)
            if not ent or not ent.config_entry_id:
                continue
            c = all_coords.get(ent.config_entry_id)
            if c is not None:
                coordinators[ent.config_entry_id] = c

    # 3) no explicit target -> all instances
    if not coordinators and not device_ids and not entity_ids and not area_ids:
        coordinators.update(all_coords)

    return list(coordinators.values())


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Small Grow Tent Controller integration.

    This is called once at Home Assistant startup. We register services here so they
    are not duplicated per config entry.
    """
    data = _domain_data(hass)
    if data[_DATA_SERVICES_REGISTERED]:
        return True

    async def _handle_refresh(call: ServiceCall) -> None:
        for c in _service_coordinators(hass, call):
            await c.async_request_refresh()

    async def _handle_set_stage(call: ServiceCall) -> None:
        stage = call.data.get("stage")
        if stage not in STAGE_TARGET_VPD_KPA:
            raise ServiceValidationError(
                f"Invalid stage '{stage}'. Valid: {', '.join(STAGE_TARGET_VPD_KPA.keys())}"
            )

        for c in _service_coordinators(hass, call):
            stage_eid = c.entity_id("select", "stage")
            await hass.services.async_call(
                "select",
                "select_option",
                {ATTR_ENTITY_ID: stage_eid, "option": stage},
                blocking=False,
            )

    async def _handle_set_enabled(call: ServiceCall) -> None:
        enabled = call.data.get("enabled")
        if enabled is None:
            raise ServiceValidationError("Missing required field: enabled")
        service = "turn_on" if bool(enabled) else "turn_off"

        for c in _service_coordinators(hass, call):
            controller_eid = c.entity_id("switch", "controller")
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

    data[_DATA_SERVICES_REGISTERED] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry (one grow tent/room instance)."""
    coordinator = GrowTentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    data = _domain_data(hass)
    data[_DATA_COORDINATORS][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = _domain_data(hass)
        data[_DATA_COORDINATORS].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
