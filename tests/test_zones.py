"""Light zones grouped into rooms (areas): neighbours and the room switch."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bright_rooms.const import (
    DOMAIN,
    ROOM_DEFAULTS,
    SETTINGS_DEFAULTS,
    SUBENTRY_ROOM,
)

from .helpers import FakeLights, advance, settle

COOK, TABLE, LIVING = (
    "binary_sensor.cooktop_presence",
    "binary_sensor.table_presence",
    "binary_sensor.living_presence",
)
LUX = "sensor.kitchen_illuminance"


def zone(name: str, area: str, sensor: str, light: str, **extra: Any) -> dict:
    return {"name": name, "area": area, "sensor": sensor, "light": light, **extra}


async def make_zones(hass: HomeAssistant, freezer: FrozenDateTimeFactory, *zones: dict):
    """Set up the entry with these light zones (areas created by name), at 20:00."""
    await hass.config.async_set_time_zone("Europe/Rome")
    freezer.move_to("2026-01-12 20:00:00+01:00")
    areas = ar.async_get(hass)
    hass.states.async_set(LUX, "10", {"device_class": "illuminance"})
    subentries = []
    for z in zones:
        area = areas.async_get_area_by_name(z["area"]) or areas.async_create(z["area"])
        hass.states.async_set(z["sensor"], "off")
        hass.states.async_set(
            z["light"],
            "off",
            {"supported_color_modes": ["onoff"], "color_mode": "onoff"},
        )
        extra = {
            k: v
            for k, v in z.items()
            if k not in ("name", "area", "sensor", "light", "id")
        }
        subentries.append(
            ConfigSubentryData(
                subentry_type=SUBENTRY_ROOM,
                title=z["name"],
                unique_id=None,
                data={
                    **ROOM_DEFAULTS,
                    "name": z["name"],
                    "area": area.id,
                    "presence_sensors": [z["sensor"]],
                    "lights": [z["light"]],
                    "illuminance_sensor": LUX,
                    "dim_percent": 100,
                    **extra,
                },
                **({"subentry_id": z["id"]} if "id" in z else {}),
            )
        )
    freezer.tick(timedelta(minutes=10))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bright Rooms",
        data={},
        options=dict(SETTINGS_DEFAULTS),
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, FakeLights(hass)


def by_name(entry, name: str):
    return next(z for z in entry.runtime_data.rooms.values() if z.name == name)


def kitchen_zones(**cook_extra):
    return (
        zone("Cooktop", "Kitchen", COOK, "light.cooktop", id="cooktop", **cook_extra),
        zone("Table", "Kitchen", TABLE, "light.table", id="table"),
        zone("Sofa", "Living room", LIVING, "light.sofa", id="sofa"),
    )


async def test_zones_of_an_area_are_neighbours(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _lights = await make_zones(hass, freezer, *kitchen_zones())
    cook = by_name(entry, "Cooktop")
    assert cook.neighbors() == {
        "auto": [TABLE],
        "manual_zones": [],
        "sensors": [],
        "effective": [TABLE],
    }
    assert by_name(entry, "Table").neighbors()["effective"] == [COOK]
    assert by_name(entry, "Sofa").neighbors()["effective"] == []
    # Cooking, then sitting at the table: the cooktop waits for the table.
    hass.states.async_set(COOK, "on")
    await settle(hass)
    hass.states.async_set(TABLE, "on")
    await settle(hass)
    hass.states.async_set(COOK, "off")
    await settle(hass)
    assert cook.status == "waiting" and cook.zone_occupied
    await advance(hass, freezer, 60, step=10)
    assert hass.states.get("light.cooktop").state == "on"
    hass.states.async_set(TABLE, "off")
    await advance(hass, freezer, 30)
    await settle(hass)
    assert hass.states.get("light.cooktop").state == "off"


async def test_automatic_neighbours_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make_zones(hass, freezer, *kitchen_zones(auto_neighbors=False))
    cook = by_name(entry, "Cooktop")
    assert cook.neighbors()["effective"] == []
    hass.states.async_set(TABLE, "on")
    hass.states.async_set(COOK, "on")
    await settle(hass)
    hass.states.async_set(COOK, "off")
    await advance(hass, freezer, 30)
    await settle(hass)
    assert hass.states.get("light.cooktop").state == "off"


async def test_manual_neighbour_zone_of_another_area(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make_zones(
        hass,
        freezer,
        *kitchen_zones(neighbor_zones=["sofa"], zone_sensors=["binary_sensor.hall"]),
    )
    assert by_name(entry, "Cooktop").neighbors() == {
        "auto": [TABLE],
        "manual_zones": ["sofa"],
        "sensors": ["binary_sensor.hall"],
        "effective": [TABLE, LIVING, "binary_sensor.hall"],
    }


async def test_band_zone_sensors_replace_every_neighbour(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {"id": "b", "start": "18:00", "end": "23:00", "zone_sensors": []}
    entry, _ = await make_zones(
        hass, freezer, *kitchen_zones(neighbor_zones=["sofa"], schedule=[band])
    )
    cook = by_name(entry, "Cooktop")
    assert cook.effective()["zone_sensors"] == []
    hass.states.async_set(TABLE, "on")
    hass.states.async_set(COOK, "on")
    await settle(hass)
    hass.states.async_set(COOK, "off")
    await advance(hass, freezer, 30)
    await settle(hass)
    assert hass.states.get("light.cooktop").state == "off"


async def test_existing_kitchen_config_behaves_the_same(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Two zones of 0.1.x in one area, each listing the other's sensor."""
    entry, _ = await make_zones(
        hass,
        freezer,
        zone("Cooktop", "Kitchen", COOK, "light.cooktop", zone_sensors=[TABLE]),
        zone("Table", "Kitchen", TABLE, "light.table", zone_sensors=[COOK]),
    )
    for name, other in (("Cooktop", TABLE), ("Table", COOK)):
        z = by_name(entry, name)
        assert z.neighbors()["effective"] == [other]
        assert z.effective()["zone_sensors"] == [other]


async def test_deleted_zone_leaves_neighbours_and_bands(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {"id": "b", "light": "dark", "light_room": "table", "empty_wait": 60}
    entry, _ = await make_zones(
        hass, freezer, *kitchen_zones(neighbor_zones=["table", "sofa"], schedule=[band])
    )
    hass.config_entries.async_remove_subentry(entry, "table")
    await hass.async_block_till_done()
    data = entry.subentries["cooktop"].data
    assert data["neighbor_zones"] == ["sofa"]
    assert data["schedule"][0]["light_room"] is None  # now the zone's own light
    assert by_name(entry, "Cooktop").neighbors()["effective"] == [LIVING]


async def test_room_switch(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry, _ = await make_zones(hass, freezer, *kitchen_zones())
    engine = entry.runtime_data
    kitchen_area = by_name(entry, "Cooktop").cfg.area_id
    reg = er.async_get(hass)
    switch = reg.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_area_{kitchen_area}_automatic"
    )
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    await hass.async_block_till_done()
    assert not by_name(entry, "Cooktop").enabled and not by_name(entry, "Table").enabled
    assert by_name(entry, "Sofa").enabled
    assert hass.states.get(switch).state == "off"
    engine.set_room_enabled("table", True)
    await hass.async_block_till_done()
    assert hass.states.get(switch).state == "on"  # any zone on
    # The zones' own switches keep their entity ids.
    assert reg.async_get_entity_id("switch", DOMAIN, "cooktop_automatic")


async def test_snapshot_areas_and_area_command(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    entry, _ = await make_zones(hass, freezer, *kitchen_zones(neighbor_zones=["sofa"]))
    kitchen_area = by_name(entry, "Cooktop").cfg.area_id
    living_area = by_name(entry, "Sofa").cfg.area_id
    await client.send_json_auto_id({"type": "bright_rooms/rooms"})
    snap = (await client.receive_json())["result"]
    assert snap["areas"] == [
        {
            "area_id": kitchen_area,
            "name": "Kitchen",
            "zone_ids": ["cooktop", "table"],
            "enabled": True,
        },
        {
            "area_id": living_area,
            "name": "Living room",
            "zone_ids": ["sofa"],
            "enabled": True,
        },
    ]
    cook = next(r for r in snap["rooms"] if r["id"] == "cooktop")
    assert cook["neighbors"] == {
        "auto": [TABLE],
        "manual_zones": ["sofa"],
        "sensors": [],
        "effective": [TABLE, LIVING],
    }
    assert cook["config"]["auto_neighbors"] is True
    assert cook["config"]["neighbor_zones"] == ["sofa"]

    await client.send_json_auto_id(
        {
            "type": "bright_rooms/area/set_enabled",
            "area_id": kitchen_area,
            "enabled": False,
        }
    )
    assert (await client.receive_json())["success"]
    assert not by_name(entry, "Table").enabled
    await client.send_json_auto_id(
        {
            "type": "bright_rooms/area/set_enabled",
            "area_id": "nowhere",
            "enabled": False,
        }
    )
    assert (await client.receive_json())["error"]["code"] == "not_found"

    # The neighbour field offers the other zones; an invalid one is refused.
    await client.send_json_auto_id(
        {"type": "bright_rooms/schema", "room_id": "cooktop"}
    )
    res = (await client.receive_json())["result"]
    field = next(f for f in res["schema"] if f["name"] == "neighbor_zones")
    options = field["selector"]["select"]["options"]
    assert [o["value"] for o in options] == ["sofa", "table"]
    for bad in (["cooktop"], ["ghost"]):
        await client.send_json_auto_id(
            {
                "type": "bright_rooms/room/save",
                "room_id": "cooktop",
                "data": {**res["values"], "neighbor_zones": bad},
            }
        )
        result = (await client.receive_json())["result"]
        assert result["errors"] == {"neighbor_zones": "neighbor_invalid"}


async def test_room_device_removed_with_its_last_zone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make_zones(hass, freezer, *kitchen_zones())
    living_area = by_name(entry, "Sofa").cfg.area_id
    devices = dr.async_get(hass)
    key = (DOMAIN, f"area_{living_area}")
    assert devices.async_get_device_by_identifier(key, entry.entry_id)
    hass.config_entries.async_remove_subentry(entry, "sofa")
    await hass.async_block_till_done()
    assert devices.async_get_device_by_identifier(key, entry.entry_id) is None


async def test_explicit_empty_lists_are_saved(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    """Saving `[]` clears a list, for a zone without bands and one with bands."""
    client = await hass_ws_client(hass)
    band = {"id": "b", "start": "06:00", "end": "08:00", "empty_wait": 60}
    entry, _ = await make_zones(
        hass,
        freezer,
        zone(
            "Cooktop",
            "Kitchen",
            COOK,
            "light.cooktop",
            id="cooktop",
            zone_sensors=[TABLE],
            schedule=[band],
        ),
        zone(
            "Table",
            "Kitchen",
            TABLE,
            "light.table",
            id="table",
            zone_sensors=[COOK],
            neighbor_zones=["sofa"],
            other_lights=["light.sofa"],
        ),
        zone("Sofa", "Living room", LIVING, "light.sofa", id="sofa"),
    )
    await client.send_json_auto_id({"type": "bright_rooms/rooms"})
    snap = (await client.receive_json())["result"]
    for zone_id in ("table", "cooktop"):
        config = next(r for r in snap["rooms"] if r["id"] == zone_id)["config"]
        await client.send_json_auto_id(
            {
                "type": "bright_rooms/room/save",
                "room_id": zone_id,
                "data": {
                    **config,
                    "zone_sensors": [],
                    "neighbor_zones": [],
                    "other_lights": [],
                },
            }
        )
        assert (await client.receive_json())["result"] == {"room_id": zone_id}
        await hass.async_block_till_done()
        data = entry.subentries[zone_id].data
        assert data["zone_sensors"] == []
        assert data["neighbor_zones"] == []
        assert data["other_lights"] == []
    # Reloaded twice: still empty, also in the snapshot.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await client.send_json_auto_id({"type": "bright_rooms/rooms"})
    snap = (await client.receive_json())["result"]
    for zone_id in ("table", "cooktop"):
        room = next(r for r in snap["rooms"] if r["id"] == zone_id)
        assert room["config"]["zone_sensors"] == []
        assert room["neighbors"]["sensors"] == []
        assert room["neighbors"]["manual_zones"] == []
    # Only the automatic neighbour is left (the other zone of the same area).
    table = next(r for r in snap["rooms"] if r["id"] == "table")
    assert table["neighbors"]["effective"] == [COOK]
    # The zone with a band keeps it.
    assert [b["id"] for b in entry.subentries["cooktop"].data["schedule"]] == ["b"]
