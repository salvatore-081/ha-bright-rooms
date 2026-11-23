"""Tests for the config, options and room flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar

from custom_components.bright_rooms.const import (
    CONF_AREA,
    CONF_BRIGHT_ABOVE,
    CONF_BRIGHTNESS_DARK_LUX,
    CONF_BRIGHTNESS_FULL_LUX,
    CONF_DARK_BELOW,
    CONF_EMPTY_WAIT,
    CONF_LEARN_WEIGHT,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_PRESENCE_SENSORS,
    CONF_SETTLE_SECONDS,
    DOMAIN,
    ROOM_DEFAULTS,
    SETTINGS_DEFAULTS,
    SUBENTRY_ROOM,
)


async def _create(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bright Rooms"
    entry = result["result"]
    assert dict(entry.options) == SETTINGS_DEFAULTS
    return entry


async def test_create_single_entry(hass: HomeAssistant) -> None:
    await _create(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


def _room(area_id: str, name: str = "Kitchen", **extra):
    return {
        **ROOM_DEFAULTS,
        CONF_NAME: name,
        CONF_AREA: area_id,
        CONF_PRESENCE_SENSORS: ["binary_sensor.a"],
        CONF_LIGHTS: ["light.a"],
        **extra,
    }


async def test_room_subentry(hass: HomeAssistant) -> None:
    entry = await _create(hass)
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    hall = areas.async_create("Hall")

    async def add(data):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_ROOM), context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        return await hass.config_entries.subentries.async_configure(
            result["flow_id"], data
        )

    data = _room(kitchen.id)
    del data[CONF_PRESENCE_SENSORS], data[CONF_LIGHTS]
    result = await add(
        {
            **data,
            CONF_DARK_BELOW: 80,
            CONF_BRIGHT_ABOVE: 80,
            CONF_BRIGHTNESS_FULL_LUX: 5,
        }
    )
    assert result["errors"] == {
        CONF_PRESENCE_SENSORS: "no_presence",
        CONF_LIGHTS: "no_lights",
        CONF_BRIGHT_ABOVE: "bright_not_above_dark",
        CONF_BRIGHTNESS_FULL_LUX: "brightness_lux_order",
    }

    result = await add(_room(kitchen.id, name=" Cooktop "))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cooktop"
    subentry = next(iter(entry.subentries.values()))
    assert subentry.unique_id is None
    assert subentry.data[CONF_NAME] == "Cooktop"
    assert subentry.data["schedule"] == []
    assert subentry.data[CONF_EMPTY_WAIT] == 30
    assert isinstance(subentry.data[CONF_EMPTY_WAIT], int)

    # Names must differ, ignoring case; areas may be shared.
    result = await add(_room(hall.id, name="COOKTOP", **{CONF_LIGHTS: ["light.b"]}))
    assert result["errors"] == {CONF_NAME: "name_taken"}
    result = await add(_room(kitchen.id, name="Table"))
    assert result["errors"] == {CONF_LIGHTS: "light_in_other_room"}
    result = await add(_room(kitchen.id, name="Table", **{CONF_LIGHTS: ["light.b"]}))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert sorted(s.title for s in entry.subentries.values()) == ["Cooktop", "Table"]

    # Edit the room: its own lights are not "in another room".
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _room(kitchen.id, name="cooktop", **{CONF_EMPTY_WAIT: 60.0})
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry.subentry_id].data[CONF_EMPTY_WAIT] == 60

    # Time bands are edited in the panel: the flow keeps them.
    band = {
        "id": "b1",
        "name": None,
        "start": "22:00",
        "end": "06:00",
        "days": [],
        "empty_wait": 600,
        "zone_wait": None,
    }
    sub = entry.subentries[subentry.subentry_id]
    hass.config_entries.async_update_subentry(
        entry, sub, data={**sub.data, "schedule": [band]}
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _room(kitchen.id, name="cooktop", **{CONF_EMPTY_WAIT: 45})
    )
    assert result["reason"] == "reconfigure_successful"
    data = entry.subentries[subentry.subentry_id].data
    assert data[CONF_EMPTY_WAIT] == 45
    assert data["schedule"] == [band]
    assert entry.subentries[subentry.subentry_id].title == "cooktop"


async def test_brightness_lux_equal_is_an_error(hass: HomeAssistant) -> None:
    entry = await _create(hass)
    kitchen = ar.async_get(hass).async_create("Kitchen")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        _room(
            kitchen.id, **{CONF_BRIGHTNESS_DARK_LUX: 50, CONF_BRIGHTNESS_FULL_LUX: 50}
        ),
    )
    assert result["errors"] == {CONF_BRIGHTNESS_FULL_LUX: "brightness_lux_order"}


async def test_options(hass: HomeAssistant) -> None:
    entry = await _create(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**SETTINGS_DEFAULTS, CONF_SETTLE_SECONDS: 40.0, CONF_LEARN_WEIGHT: 0.5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SETTLE_SECONDS] == 40
    assert entry.options[CONF_LEARN_WEIGHT] == 0.5
