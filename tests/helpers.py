"""Shared helpers: a kitchen with fake lights, sensors and the integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntry, ConfigSubentryData
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.bright_rooms.const import (
    CONF_AREA,
    CONF_ILLUMINANCE_SENSOR,
    CONF_LIGHTS,
    CONF_PRESENCE_SENSORS,
    CONF_ZONE_SENSORS,
    DOMAIN,
    ROOM_DEFAULTS,
    SETTINGS_DEFAULTS,
    SUBENTRY_ROOM,
)
from custom_components.bright_rooms.engine import RoomEngine

PRESENCE = "binary_sensor.kitchen_presence"
ZONE = "binary_sensor.table_presence"
LUX = "sensor.kitchen_illuminance"
CEILING = "light.ceiling"  # dimmable
STRIP = "light.strip"  # on/off
OTHER = "light.living_room"

DIMMABLE = {"supported_color_modes": ["brightness"], "color_mode": "brightness"}
ONOFF = {"supported_color_modes": ["onoff"], "color_mode": "onoff"}


def set_light(
    hass: HomeAssistant, entity_id: str, state: str, brightness: int | None = None, **kw
) -> None:
    """Change a light as someone else would (no Bright Rooms context)."""
    base = DIMMABLE if entity_id != STRIP else ONOFF
    attrs: dict[str, Any] = {**base, "friendly_name": entity_id.split(".")[1].title()}
    if state == "on" and entity_id != STRIP:
        attrs["brightness"] = 255 if brightness is None else brightness
    hass.states.async_set(entity_id, state, attrs, **kw)


class FakeLights:
    """light.turn_on / light.turn_off that change the states like a real light."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Register the services (after setup: they replace the light component's)."""
        self.hass = hass
        self.calls: list[ServiceCall] = []
        self.failures = 0  # the next calls that raise (and do nothing)
        self.deaf: set[str] = set()  # lights that ignore commands
        hass.services.async_register("light", "turn_on", self._handle)
        hass.services.async_register("light", "turn_off", self._handle)

    @callback
    def _handle(self, call: ServiceCall) -> None:
        self.calls.append(call)
        if self.failures:
            self.failures -= 1
            raise HomeAssistantError("Device communication error")
        ids = call.data[ATTR_ENTITY_ID]
        for entity_id in [ids] if isinstance(ids, str) else ids:
            if entity_id in self.deaf:
                continue
            old = self.hass.states.get(entity_id)
            attrs = dict(old.attributes) if old else {}
            if call.service == "turn_off":
                attrs.pop("brightness", None)
                self.hass.states.async_set(
                    entity_id, "off", attrs, context=call.context
                )
                continue
            if entity_id != STRIP:
                if "brightness_pct" in call.data:
                    attrs["brightness"] = round(call.data["brightness_pct"] * 255 / 100)
                elif "brightness" in call.data:
                    attrs["brightness"] = call.data["brightness"]
                else:
                    attrs.setdefault("brightness", 255)
            self.hass.states.async_set(entity_id, "on", attrs, context=call.context)

    def of(self, service: str) -> list[ServiceCall]:
        """Calls of one service."""
        return [c for c in self.calls if c.service == service]

    def clear(self) -> None:
        """Forget the calls so far."""
        self.calls.clear()


async def make(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    *,
    lux: str | None = "10",
    options: dict[str, Any] | None = None,
    room_id: str | None = None,
    entry_id: str | None = None,
    **room: Any,
) -> tuple[ConfigEntry, FakeLights]:
    """Set up the integration with one room, the kitchen, at 20:00."""
    await hass.config.async_set_time_zone("Europe/Rome")
    freezer.move_to("2026-01-12 20:00:00+01:00")
    area = ar.async_get(hass).async_get_area_by_name("Kitchen") or ar.async_get(
        hass
    ).async_create("Kitchen")
    for sensor in (PRESENCE, ZONE):
        if hass.states.get(sensor) is None:
            hass.states.async_set(sensor, "off")
    if lux is not None:
        hass.states.async_set(LUX, lux, {"device_class": "illuminance"})
    for light in (CEILING, STRIP, OTHER):
        if hass.states.get(light) is None:
            set_light(hass, light, "off")
    # Everything has been as it is for a while.
    freezer.tick(timedelta(minutes=10))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bright Rooms",
        **({"entry_id": entry_id} if entry_id else {}),
        data={},
        options={**SETTINGS_DEFAULTS, **(options or {})},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_ROOM,
                title="Kitchen",
                unique_id=area.id,
                data={
                    **ROOM_DEFAULTS,
                    CONF_AREA: area.id,
                    CONF_PRESENCE_SENSORS: [PRESENCE],
                    CONF_ZONE_SENSORS: [ZONE],
                    CONF_LIGHTS: [CEILING, STRIP],
                    CONF_ILLUMINANCE_SENSOR: LUX,
                    **room,
                },
                **({"subentry_id": room_id} if room_id else {}),
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, FakeLights(hass)


def kitchen(entry: ConfigEntry) -> RoomEngine:
    """The engine of the only room."""
    (room,) = entry.runtime_data.rooms.values()
    return room


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float, step: float = 1
) -> None:
    """Let time pass, firing timers on the way."""
    done = 0.0
    while done < seconds:
        tick = min(step, seconds - done)
        freezer.tick(timedelta(seconds=tick))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        done += tick


async def settle(hass: HomeAssistant) -> None:
    """Let the commands sent by the engine run."""
    await hass.async_block_till_done()


async def presence(hass: HomeAssistant, on: bool) -> None:
    """The kitchen's presence sensor."""
    hass.states.async_set(PRESENCE, "on" if on else "off")
    await hass.async_block_till_done()


async def lux(hass: HomeAssistant, value: float | str) -> None:
    """A new reading of the illuminance sensor."""
    hass.states.async_set(LUX, str(value), {"device_class": "illuminance"})
    await hass.async_block_till_done()
