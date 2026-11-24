"""Bright Rooms: room lights switched by presence and by the light of the day."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from . import panel, websocket_api
from .const import (
    CONF_NEIGHBOR_ZONES,
    CONF_SCHEDULE,
    DOMAIN,
    SUBENTRY_ROOM,
    TITLE,
)
from .engine import BrightRoomsEngine
from .store import BrightRoomsStore

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type BrightRoomsConfigEntry = ConfigEntry[BrightRoomsEngine]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the WebSocket API of the panel."""
    websocket_api.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BrightRoomsConfigEntry) -> bool:
    """Set up Bright Rooms from a config entry."""
    _remove_dangling_references(hass, entry)
    engine = BrightRoomsEngine(hass, entry)
    entry.runtime_data = engine
    devices = dr.async_get(hass)
    # The entry's device first, then one per room (area): the light zones'
    # devices hang from their room's (via_device_id).
    engine.device_id = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=TITLE,
        entry_type=dr.DeviceEntryType.SERVICE,
    ).id
    for area_id in engine.area_ids():
        name = engine.area_name(area_id)
        engine.area_device_ids[area_id] = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, area_device_key(area_id))},
            name=f"{TITLE} {name}",
            suggested_area=name,
            entry_type=dr.DeviceEntryType.SERVICE,
            via_device_id=engine.device_id,
        ).id
    # Rooms left without light zones lose their device.
    keep = {area_device_key(a) for a in engine.area_ids()}
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if any(
            domain == DOMAIN and key.startswith(AREA_PREFIX) and key not in keep
            for domain, key in device.identifiers
        ):
            devices.async_remove_device(device.id)
    await engine.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    await panel.async_register(hass)
    return True


AREA_PREFIX = "area_"


def area_device_key(area_id: str) -> str:
    """Identifier of a room's device."""
    return f"{AREA_PREFIX}{area_id}"


def _remove_dangling_references(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A deleted light zone leaves the others' neighbours and bands.

    Bands whose light condition referred to it fall back to the zone's own
    light (`light_room` null).
    """
    zones = {
        sid
        for sid, sub in entry.subentries.items()
        if sub.subentry_type == SUBENTRY_ROOM
    }
    for sub in list(entry.subentries.values()):
        if sub.subentry_type != SUBENTRY_ROOM:
            continue
        data = dict(sub.data)
        neighbors = [z for z in data.get(CONF_NEIGHBOR_ZONES) or [] if z in zones]
        bands = [
            {**band, "light_room": None}
            if band.get("light_room") and band["light_room"] not in zones
            else band
            for band in data.get(CONF_SCHEDULE) or []
        ]
        changed = {}
        if neighbors != list(data.get(CONF_NEIGHBOR_ZONES) or []):
            changed[CONF_NEIGHBOR_ZONES] = neighbors
        if bands != list(data.get(CONF_SCHEDULE) or []):
            changed[CONF_SCHEDULE] = bands
        if changed:
            hass.config_entries.async_update_subentry(
                entry, sub, data={**data, **changed}
            )


async def _async_entry_updated(
    hass: HomeAssistant, entry: BrightRoomsConfigEntry
) -> None:
    """Rooms or settings changed: rebuild everything."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: BrightRoomsConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.async_stop()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # The panel stays through a reload (a zone or the settings saved): removing
    # it, even for a moment, sends the browser away from it. It goes when the
    # entry is disabled or removed.
    if entry.disabled_by is not None:
        panel.async_unregister(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the learned contributions and the panel of a removed entry."""
    await BrightRoomsStore(hass, entry.entry_id).async_remove()
    panel.async_unregister(hass)  # single config entry
