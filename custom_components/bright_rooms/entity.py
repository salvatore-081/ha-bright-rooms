"""Base entity of Bright Rooms: one device per room."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, TITLE
from .engine import BrightRoomsEngine, RoomEngine, room_signal


class BrightRoomsRoomEntity(Entity):
    """Entity of one room (one device per room, in the room's area)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, engine: BrightRoomsEngine, room: RoomEngine, key: str) -> None:
        """Initialize."""
        self.engine = engine
        self.room = room
        self._attr_translation_key = key
        self._attr_unique_id = f"{room.subentry_id}_{key}"
        area = ar.async_get(engine.hass).async_get_area(room.cfg.area_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.subentry_id)},
            name=f"{TITLE} {room.name}",
            suggested_area=area.name if area else None,
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=engine.area_device_ids.get(room.cfg.area_id)
            or engine.device_id,
        )

    async def async_added_to_hass(self) -> None:
        """Follow the room's updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, room_signal(self.room.subentry_id), self._on_update
            )
        )

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()
