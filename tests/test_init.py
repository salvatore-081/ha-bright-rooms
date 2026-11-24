"""Entities, saved state, reloads and removal."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.bright_rooms.const import DOMAIN

from .helpers import CEILING, STRIP, advance, kitchen, make, presence, settle

PREFIX = "kitchen_bright_rooms_kitchen"
ENTRY = "entry0000000000000000000000000"
ROOM = "room00000000000000000000000000"


async def test_entities(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry, _ = await make(hass, freezer)
    ambient = hass.states.get(f"sensor.{PREFIX}_ambient_light")
    assert ambient.state == "10"
    assert ambient.attributes["unit_of_measurement"] == "lx"
    assert ambient.attributes["device_class"] == "illuminance"
    assert ambient.attributes["raw"] == 10
    assert hass.states.get(f"binary_sensor.{PREFIX}_dark").state == "on"
    status = hass.states.get(f"sensor.{PREFIX}_status")
    assert status.state == "off"
    assert status.attributes["options"] == [
        "disabled",
        "off",
        "on",
        "waiting",
        "dimmed",
    ]
    assert status.attributes["last_action"] is None
    assert hass.states.get(f"switch.{PREFIX}_automatic").state == "on"
    contribution = hass.states.get(f"sensor.{PREFIX}_contribution_ceiling")
    assert contribution.state == "unknown"
    assert contribution.attributes["samples"] == 0

    reg = er.async_get(hass)
    entity = reg.async_get(f"sensor.{PREFIX}_contribution_strip")
    assert entity.unique_id == f"{kitchen(entry).subentry_id}_contribution_strip"
    assert entity.entity_category is er.EntityCategory.DIAGNOSTIC
    # One device per room, in its area, under the entry's device.
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.name == "Bright Rooms Kitchen"
    assert device.area_id == kitchen(entry).cfg.area_id
    # The zone's device hangs from its room's (the area), which hangs from the entry's.
    area_device = dr.async_get(hass).async_get(device.via_device_id)
    assert area_device.name == "Bright Rooms Kitchen"
    assert area_device.area_id == kitchen(entry).cfg.area_id
    assert area_device.via_device_id == entry.runtime_data.device_id

    await presence(hass, True)
    await settle(hass)
    status = hass.states.get(f"sensor.{PREFIX}_status")
    assert status.state == "on"
    assert status.attributes["last_action"] == "turned_on"
    assert status.attributes["reason"] == "presence_dark"
    await presence(hass, False)
    status = hass.states.get(f"sensor.{PREFIX}_status")
    assert status.state == "waiting"
    assert status.attributes["deadline"] is not None

    hass.states.async_set("sensor.kitchen_illuminance", "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(f"binary_sensor.{PREFIX}_dark").state == "unknown"


async def test_switch_and_saved_state(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    entry, _lights = await make(hass, freezer, entry_id=ENTRY, room_id=ROOM)
    switch = f"switch.{PREFIX}_automatic"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    assert hass.states.get(f"sensor.{PREFIX}_status").state == "disabled"
    entry.runtime_data.set_contribution(ROOM, CEILING, 120)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.{PREFIX}_contribution_ceiling").state == "120"

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    saved = hass_storage[f"{DOMAIN}.{ENTRY}"]["data"]["rooms"][ROOM]
    assert saved["enabled"] is False
    assert saved["contributions"][CEILING]["value"] == 120
    assert hass.states.get(switch).state == "off"
    assert kitchen(entry).contribution(CEILING).value == 120

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    assert kitchen(entry).enabled is True


async def test_saved_state_of_removed_lights_dropped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    hass_storage[f"{DOMAIN}.{ENTRY}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{ENTRY}",
        "data": {
            "rooms": {
                ROOM: {
                    "enabled": True,
                    "contributions": {
                        CEILING: {"value": 80, "samples": 3, "updated": None},
                        "light.gone": {"value": 5, "samples": 1, "updated": None},
                    },
                },
                "oldroom": {"enabled": False, "contributions": {}},
            }
        },
    }
    entry, _ = await make(hass, freezer, entry_id=ENTRY, room_id=ROOM)
    assert kitchen(entry).contribution(CEILING).samples == 3
    await hass.config_entries.async_unload(entry.entry_id)
    rooms = hass_storage[f"{DOMAIN}.{ENTRY}"]["data"]["rooms"]
    assert list(rooms) == [ROOM]
    assert list(rooms[ROOM]["contributions"]) == [CEILING]


async def test_reload_restarts_turning_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The turn-off in progress is dropped, then started again after the grace."""
    entry, lights = await make(hass, freezer)
    await presence(hass, True)
    await settle(hass)
    await presence(hass, False)
    lights.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, 59)
    assert lights.calls == []
    assert hass.states.get(STRIP).state == "on"
    await advance(hass, freezer, 11)
    await settle(hass)
    assert hass.states.get(STRIP).state == "off"
    assert hass.states.get(CEILING).state == "off"


async def test_unload_and_remove(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    entry, _ = await make(hass, freezer, entry_id=ENTRY)
    await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert f"{DOMAIN}.{ENTRY}" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{ENTRY}" not in hass_storage
