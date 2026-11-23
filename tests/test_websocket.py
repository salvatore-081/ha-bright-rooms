"""Tests for the WebSocket API of the panel and the card, and the panel itself."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bright_rooms import panel
from custom_components.bright_rooms.const import (
    CONF_AREA,
    CONF_BRIGHT_ABOVE,
    CONF_EMPTY_WAIT,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_PRESENCE_SENSORS,
    CONF_SETTLE_SECONDS,
    SUBENTRY_ROOM,
)

from .helpers import (
    CEILING,
    LUX,
    PRESENCE,
    STRIP,
    advance,
    kitchen,
    make,
    presence,
    settle,
)


async def _call(client, **msg):
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_rooms_and_subscribe(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    res = await _call(client, type="bright_rooms/rooms")
    snap = res["result"]
    assert snap["entry_id"] == entry.entry_id
    assert snap["settings"] == {
        "settle_seconds": 75,
        "learn_ambient_max": 60,
        "learn_min_previous": 90,
        "learn_weight": 0.2,
    }
    (room,) = snap["rooms"]
    assert room["name"] == "Kitchen"
    assert room["id"] == kitchen(entry).subentry_id
    assert room["enabled"] is True
    assert room["status"] == "off"
    assert (room["occupied"], room["zone_occupied"]) == (False, False)
    assert (room["raw_lux"], room["ambient"], room["held"], room["dark"]) == (
        10,
        10,
        False,
        True,
    )
    assert room["deadline"] is None and room["last_action"] is None
    assert room["config"][CONF_PRESENCE_SENSORS] == [PRESENCE]
    assert room["config"]["illuminance_sensor"] == LUX
    assert room["config"]["other_lights"] == []
    assert room["config"][CONF_EMPTY_WAIT] == 30
    assert room["lights"] == [
        {
            "entity_id": CEILING,
            "name": "Ceiling",
            "state": "off",
            "brightness": None,
            "dimmable": True,
            "contribution": None,
            "samples": 0,
            "updated": None,
        },
        {
            "entity_id": STRIP,
            "name": "Strip",
            "state": "off",
            "brightness": None,
            "dimmable": False,
            "contribution": None,
            "samples": 0,
            "updated": None,
        },
    ]
    assert room["sensor_entities"] == []

    res = await _call(client, type="bright_rooms/subscribe")
    assert res["success"]
    event = (await client.receive_json())["event"]
    assert event["rooms"][0]["status"] == "off"
    await presence(hass, True)
    await settle(hass)
    await advance(hass, freezer, 1)
    event = (await client.receive_json())["event"]
    room = event["rooms"][0]
    assert room["occupied"] is True
    assert room["status"] == "on"
    assert room["last_action"]["action"] == "turned_on"
    assert room["lights"][0]["brightness"] == 255


async def test_rooms_sharing_an_area_in_name_order(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    """The kitchen room was saved without a name: it is named after its area."""
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    area_id = kitchen(entry).cfg.area_id
    table = {
        CONF_NAME: "Dining table",
        CONF_AREA: area_id,
        CONF_PRESENCE_SENSORS: ["binary_sensor.table"],
        CONF_LIGHTS: ["light.table_lamp"],
    }
    res = await _call(
        client, type="bright_rooms/room/save", data={**table, CONF_NAME: "kitchen"}
    )
    assert res["result"]["errors"] == {CONF_NAME: "name_taken"}
    res = await _call(client, type="bright_rooms/room/save", data=table)
    assert "room_id" in res["result"]
    await hass.async_block_till_done()
    res = await _call(client, type="bright_rooms/rooms")
    rooms = res["result"]["rooms"]
    assert [r["name"] for r in rooms] == ["Dining table", "Kitchen"]
    assert [r["area_id"] for r in rooms] == [area_id, area_id]
    assert rooms[0]["config"][CONF_NAME] == "Dining table"
    assert rooms[1]["config"][CONF_NAME] == "Kitchen"
    device = dr.async_get(hass).async_get_device_by_identifier(
        ("bright_rooms", rooms[0]["id"]), entry.entry_id
    )
    assert device.name == "Bright Rooms Dining table"
    assert device.area_id == area_id


async def test_not_set_up_and_not_loaded(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    await hass.config_entries.async_unload(entry.entry_id)
    for command in ("bright_rooms/rooms", "bright_rooms/subscribe"):
        res = await _call(client, type=command)
        assert res["error"]["code"] == "not_loaded"
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    for command in ("bright_rooms/rooms", "bright_rooms/subscribe"):
        res = await _call(client, type=command)
        assert res["error"]["code"] == "not_found"


async def test_subscription_survives_a_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    await _call(client, type="bright_rooms/subscribe")
    await client.receive_json()
    await advance(hass, freezer, 1)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, 1)
    event = (await client.receive_json())["event"]
    assert event["rooms"][0]["name"] == "Kitchen"


async def test_schema(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    res = await _call(client, type="bright_rooms/schema")
    result = res["result"]
    assert [f["name"] for f in result["schema"]] == [
        "name",
        "area",
        "presence_sensors",
        "zone_sensors",
        "lights",
        "illuminance_sensor",
        "other_lights",
        "on_delay",
        "only_when_dark",
        "dark_below",
        "bright_above",
        "off_when_bright",
        "on_when_dark",
        "bright_minutes",
        "min_off_seconds",
        "brightness_min",
        "brightness_dark_lux",
        "brightness_full_lux",
        "empty_wait",
        "zone_wait",
        "dim_percent",
        "dim_wait",
        "transition",
    ]
    fields = {f["name"]: f for f in result["schema"]}
    assert fields["lights"]["selector"]["entity"]["domain"] == ["light"]
    assert fields["empty_wait"]["selector"]["number"]["unit_of_measurement"] == "s"
    assert result["values"][CONF_EMPTY_WAIT] == 30
    assert CONF_AREA not in result["values"]
    assert [f["name"] for f in result["settings_schema"]] == [
        "settle_seconds",
        "learn_ambient_max",
        "learn_min_previous",
        "learn_weight",
    ]
    assert result["settings"][CONF_SETTLE_SECONDS] == 75

    room_id = kitchen(entry).subentry_id
    res = await _call(client, type="bright_rooms/schema", room_id=room_id)
    values = res["result"]["values"]
    assert values[CONF_LIGHTS] == [CEILING, STRIP]
    assert values["illuminance_sensor"] == LUX
    assert values[CONF_NAME] == "Kitchen"  # saved without a name: the area's

    res = await _call(client, type="bright_rooms/schema", room_id="nope")
    assert res["error"]["code"] == "not_found"


async def test_room_save_and_delete(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    room_id = kitchen(entry).subentry_id
    hall = ar.async_get(hass).async_create("Hall")

    res = await _call(
        client,
        type="bright_rooms/room/save",
        data={
            CONF_NAME: "Hall",
            CONF_AREA: hall.id,
            CONF_LIGHTS: [CEILING],
            CONF_BRIGHT_ABOVE: 10,
        },
    )
    assert res["result"]["errors"] == {
        CONF_PRESENCE_SENSORS: "no_presence",
        CONF_LIGHTS: "light_in_other_room",
        CONF_BRIGHT_ABOVE: "bright_not_above_dark",
    }
    res = await _call(
        client,
        type="bright_rooms/room/save",
        data={CONF_NAME: "Hall", CONF_AREA: hall.id, CONF_EMPTY_WAIT: "soon"},
    )
    assert res["result"]["errors"] == {CONF_EMPTY_WAIT: "invalid"}

    # Edit: cleared optional fields come as null and go away; the rest is kept.
    data = {
        **entry.subentries[room_id].data,
        CONF_NAME: "Cooktop",
        "illuminance_sensor": None,
        CONF_EMPTY_WAIT: 45,
    }
    res = await _call(client, type="bright_rooms/room/save", room_id=room_id, data=data)
    assert res["result"] == {"room_id": room_id}
    await hass.async_block_till_done()
    saved = entry.subentries[room_id].data
    assert saved[CONF_EMPTY_WAIT] == 45
    assert "illuminance_sensor" not in saved
    assert kitchen(entry).cfg.illuminance_sensor is None  # reloaded
    assert entry.subentries[room_id].title == "Cooktop"
    assert entry.subentries[room_id].unique_id is None

    res = await _call(client, type="bright_rooms/room/delete", room_id=room_id)
    assert res["success"]
    await hass.async_block_till_done()
    assert not [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_ROOM
    ]
    assert hass.states.get("sensor.kitchen_bright_rooms_kitchen_status") is None
    res = await _call(client, type="bright_rooms/room/delete", room_id=room_id)
    assert res["error"]["code"] == "not_found"


async def test_set_enabled_and_contribution(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    room_id = kitchen(entry).subentry_id

    res = await _call(
        client, type="bright_rooms/room/set_enabled", room_id=room_id, enabled=False
    )
    assert res["success"]
    assert kitchen(entry).status == "disabled"
    res = await _call(
        client, type="bright_rooms/room/set_enabled", room_id="nope", enabled=False
    )
    assert res["error"]["code"] == "not_found"

    res = await _call(
        client,
        type="bright_rooms/contribution/set",
        room_id=room_id,
        entity_id=CEILING,
        value=85,
    )
    assert res["success"]
    c = kitchen(entry).contribution(CEILING)
    assert c.value == 85 and c.updated is not None
    res = await _call(
        client,
        type="bright_rooms/contribution/set",
        room_id=room_id,
        entity_id=CEILING,
        value=None,
    )
    assert res["success"]
    assert kitchen(entry).contribution(CEILING).value is None
    res = await _call(
        client,
        type="bright_rooms/contribution/set",
        room_id=room_id,
        entity_id="light.x",
        value=1,
    )
    assert res["error"]["code"] == "not_found"
    res = await _call(
        client,
        type="bright_rooms/contribution/set",
        room_id=room_id,
        entity_id=CEILING,
        value=-1,
    )
    assert res["error"]["code"] == "invalid_format"


async def test_settings_save(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make(hass, freezer)
    res = await _call(
        client, type="bright_rooms/settings/save", data={CONF_SETTLE_SECONDS: "many"}
    )
    assert res["result"]["errors"] == {CONF_SETTLE_SECONDS: "invalid"}
    res = await _call(
        client,
        type="bright_rooms/settings/save",
        data={
            "settle_seconds": 40,
            "learn_ambient_max": 30,
            "learn_min_previous": 60,
            "learn_weight": 0.5,
        },
    )
    assert res["result"] == {}
    await hass.async_block_till_done()
    assert entry.options["settle_seconds"] == 40
    assert entry.runtime_data.settings["learn_weight"] == 0.5


async def test_presence_sensor_settings(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    other = MockConfigEntry(domain="zha")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("zha", "sensor1")}
    )
    reg = er.async_get(hass)

    def add(domain, uid, category=er.EntityCategory.CONFIG, **kw):
        return reg.async_get_or_create(
            domain,
            "zha",
            uid,
            device_id=device.id,
            config_entry=other,
            entity_category=category,
            **kw,
        ).entity_id

    sensor = add("binary_sensor", "occupancy", category=None)
    sensitivity = add("select", "sensitivity")
    delay = add("number", "delay")
    add("sensor", "rssi", category=er.EntityCategory.DIAGNOSTIC)
    add("number", "hidden_by_user", disabled_by=er.RegistryEntryDisabler.USER)
    hass.states.async_set(sensor, "off")
    client = await hass_ws_client(hass)
    _entry, _ = await make(hass, freezer, presence_sensors=[sensor])
    res = await _call(client, type="bright_rooms/rooms")
    assert res["result"]["rooms"][0]["sensor_entities"] == sorted([sensitivity, delay])


async def test_read_only_user(
    hass: HomeAssistant, freezer, hass_ws_client, hass_read_only_access_token
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)
    entry, _ = await make(hass, freezer)
    res = await _call(client, type="bright_rooms/rooms")
    assert res["success"]  # the card works for every user
    res = await _call(client, type="bright_rooms/subscribe")
    assert res["success"]
    await client.receive_json()
    room_id = kitchen(entry).subentry_id
    for msg in (
        {"type": "bright_rooms/schema"},
        {"type": "bright_rooms/room/save", "data": {}},
        {"type": "bright_rooms/room/delete", "room_id": room_id},
        {"type": "bright_rooms/room/set_enabled", "room_id": room_id, "enabled": False},
        {
            "type": "bright_rooms/contribution/set",
            "room_id": room_id,
            "entity_id": CEILING,
            "value": 1,
        },
        {"type": "bright_rooms/settings/save", "data": {}},
    ):
        res = await _call(client, **msg)
        assert res["error"]["code"] == "unauthorized", msg


async def test_panel_registered_and_removed(
    hass: HomeAssistant, freezer, tmp_path
) -> None:
    (tmp_path / panel.PANEL_FILE).write_text("")
    (tmp_path / panel.CARD_FILE).write_text("")
    hass.config.components.add("frontend")
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with (
        patch.object(panel, "FRONTEND_DIR", tmp_path),
        patch.object(panel, "async_register_built_in_panel") as register,
        patch.object(panel, "add_extra_js_url") as add_js,
        patch.object(panel, "async_remove_panel") as remove,
        patch.object(panel, "remove_extra_js_url") as remove_js,
    ):
        entry, _ = await make(hass, freezer)
        await panel.async_register(hass)  # again: nothing new
        assert register.call_count == 1
        kwargs = register.call_args.kwargs
        assert kwargs["frontend_url_path"] == "bright-rooms"
        assert kwargs["sidebar_icon"] == "mdi:lightbulb-auto"
        assert kwargs["require_admin"] is True
        custom = kwargs["config"]["_panel_custom"]
        assert custom["name"] == "bright-rooms-panel"
        version = json.loads(
            (Path(panel.__file__).parent / "manifest.json").read_text()
        )["version"]
        assert (
            custom["js_url"] == f"/bright_rooms_files/bright-rooms-panel.js?v={version}"
        )
        add_js.assert_called_once()

        await hass.config_entries.async_unload(entry.entry_id)
        remove.assert_called_once_with(hass, "bright-rooms")
        remove_js.assert_called_once()


async def test_panel_missing_js(
    hass: HomeAssistant, freezer, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    hass.config.components.add("frontend")
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with (
        patch.object(panel, "FRONTEND_DIR", tmp_path),
        patch.object(panel, "async_register_built_in_panel") as register,
    ):
        await make(hass, freezer)
    register.assert_not_called()
    assert "install a release" in caplog.text


def test_versions_match() -> None:
    root = Path(__file__).parent.parent
    manifest = json.loads(
        (root / "custom_components/bright_rooms/manifest.json").read_text()
    )
    frontend = json.loads((root / "frontend/package.json").read_text())
    assert manifest["version"] == frontend["version"] == "0.1.2"
