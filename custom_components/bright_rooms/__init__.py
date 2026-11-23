"""Bright Rooms: room lights switched by presence and by the light of the day."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from . import panel, websocket_api
from .const import DOMAIN, TITLE
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
    engine = BrightRoomsEngine(hass, entry)
    entry.runtime_data = engine
    # The entry's device first: the room devices hang from it (via_device_id).
    engine.device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name=TITLE,
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        .id
    )
    await engine.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    await panel.async_register(hass)
    return True


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
    panel.async_unregister(hass)  # single config entry
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the learned contributions of a removed entry."""
    await BrightRoomsStore(hass, entry.entry_id).async_remove()
