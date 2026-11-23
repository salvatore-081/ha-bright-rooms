"""Sensors: ambient light, status and learned contributions of a room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import LIGHT_LUX, EntityCategory
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrightRoomsConfigEntry
from .const import Status
from .engine import BrightRoomsEngine, RoomEngine
from .entity import BrightRoomsRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrightRoomsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    engine = entry.runtime_data
    for room in engine.rooms.values():
        async_add_entities(
            [
                AmbientLightSensor(engine, room),
                StatusSensor(engine, room),
                *(ContributionSensor(engine, room, light) for light in room.cfg.lights),
            ],
            config_subentry_id=room.subentry_id,
        )


class AmbientLightSensor(BrightRoomsRoomEntity, SensorEntity):
    """Light in the room without its own lights."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX

    def __init__(self, engine: BrightRoomsEngine, room: RoomEngine) -> None:
        """Initialize."""
        super().__init__(engine, room, "ambient_light")

    @property
    def native_value(self) -> int | None:
        """Ambient light."""
        return self.room.ambient

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Raw reading, and whether the value is held."""
        return {"raw": self.room.raw_lux, "held": self.room.held}


class StatusSensor(BrightRoomsRoomEntity, SensorEntity):
    """What the room is doing."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, engine: BrightRoomsEngine, room: RoomEngine) -> None:
        """Initialize."""
        super().__init__(engine, room, "status")
        self._attr_options = [s.value for s in Status]

    @property
    def native_value(self) -> str:
        """Status."""
        return self.room.status.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Last action and next timed step."""
        last = self.room.last_action.as_dict() if self.room.last_action else None
        deadline = self.room.deadline
        return {
            "last_action": last["action"] if last else None,
            "reason": last["reason"] if last else None,
            "at": last["at"] if last else None,
            "detail": last["detail"] if last else None,
            "active_band": band.label if (band := self.room.active_band()) else None,
            "deadline": deadline.isoformat() if deadline else None,
        }


class ContributionSensor(BrightRoomsRoomEntity, SensorEntity):
    """Lux a light adds to the room's illuminance sensor at full brightness."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_suggested_display_precision = 0

    def __init__(self, engine: BrightRoomsEngine, room: RoomEngine, light: str) -> None:
        """Initialize."""
        object_id = split_entity_id(light)[1]
        super().__init__(engine, room, f"contribution_{object_id}")
        self.light = light
        self._attr_translation_key = "contribution"
        state = engine.hass.states.get(light)
        self._attr_translation_placeholders = {
            "light": state.name if state else object_id
        }

    @property
    def native_value(self) -> float | None:
        """Learned value, None until the first measurement."""
        return self.room.contribution(self.light).value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """How it was learned."""
        c = self.room.contribution(self.light)
        return {"samples": c.samples, "updated": c.updated}
