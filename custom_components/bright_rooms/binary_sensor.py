"""Binary sensor: whether a room is dark without its own lights."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrightRoomsConfigEntry
from .engine import BrightRoomsEngine, RoomEngine
from .entity import BrightRoomsRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrightRoomsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    engine = entry.runtime_data
    for room in engine.rooms.values():
        async_add_entities(
            [DarkSensor(engine, room)], config_subentry_id=room.subentry_id
        )


class DarkSensor(BrightRoomsRoomEntity, BinarySensorEntity):
    """On when the room is dark (with hysteresis); unknown without a reading."""

    def __init__(self, engine: BrightRoomsEngine, room: RoomEngine) -> None:
        """Initialize."""
        super().__init__(engine, room, "dark")

    @property
    def is_on(self) -> bool | None:
        """Dark."""
        return self.room.dark
