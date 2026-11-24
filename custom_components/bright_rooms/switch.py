"""Switches: Bright Rooms on or off in a light zone, or in a whole room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrightRoomsConfigEntry
from .const import DOMAIN, TITLE
from .engine import BrightRoomsEngine, RoomEngine
from .entity import BrightRoomsRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrightRoomsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    engine = entry.runtime_data
    for room in engine.rooms.values():
        async_add_entities(
            [AutomaticSwitch(engine, room)], config_subentry_id=room.subentry_id
        )
    async_add_entities([AreaAutomaticSwitch(engine, a) for a in engine.area_ids()])


class AutomaticSwitch(BrightRoomsRoomEntity, SwitchEntity):
    """Bright Rooms switches the room's lights (saved across restarts)."""

    def __init__(self, engine: BrightRoomsEngine, room: RoomEngine) -> None:
        """Initialize."""
        super().__init__(engine, room, "automatic")

    @property
    def is_on(self) -> bool:
        """Enabled."""
        return self.room.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the room."""
        self.room.set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the room: what is in progress stops, the lights stay as they are."""
        self.room.set_enabled(False)


class AreaAutomaticSwitch(SwitchEntity):
    """Every light zone of a room (Home Assistant area) on or off.

    On when any zone of the room is enabled.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "area_automatic"

    def __init__(self, engine: BrightRoomsEngine, area_id: str) -> None:
        """Initialize."""
        self.engine = engine
        self.area_id = area_id
        name = engine.area_name(area_id)
        self._attr_unique_id = f"{engine.entry.entry_id}_area_{area_id}_automatic"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"area_{area_id}")},
            name=f"{TITLE} {name}",
            suggested_area=name,
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=engine.device_id,
        )

    async def async_added_to_hass(self) -> None:
        """Follow every change of the entry (any zone may change)."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.engine.signal, self._on_update)
        )

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Any zone of the room enabled."""
        return self.engine.area_enabled(self.area_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable every zone of the room."""
        self.engine.set_area_enabled(self.area_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable every zone of the room."""
        self.engine.set_area_enabled(self.area_id, False)
