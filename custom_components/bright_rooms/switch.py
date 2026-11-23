"""Switch: Bright Rooms on or off in a room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up switches."""
    engine = entry.runtime_data
    for room in engine.rooms.values():
        async_add_entities(
            [AutomaticSwitch(engine, room)], config_subentry_id=room.subentry_id
        )


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
