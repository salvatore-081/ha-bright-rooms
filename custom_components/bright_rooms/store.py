"""Saved state: learned contributions and the Automatic switch of each room."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

SAVE_DELAY = 10  # seconds


@dataclass(frozen=True, slots=True)
class Contribution:
    """Lux a light adds at full brightness, and how it was learned."""

    value: float | None = None
    samples: int = 0
    updated: str | None = None  # ISO time


def storage_key(entry_id: str) -> str:
    """Key of an entry's store."""
    return f"{DOMAIN}.{entry_id}"


class BrightRoomsStore:
    """Rooms by subentry id: `enabled` and `contributions` by light."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry_id)
        )
        self._rooms: dict[str, dict[str, Any]] = {}

    async def async_load(self, rooms: dict[str, list[str]]) -> None:
        """Load, keeping only the rooms and lights configured now."""
        data = await self._store.async_load() or {}
        saved = data.get("rooms") or {}
        self._rooms = {}
        for room_id, lights in rooms.items():
            room = saved.get(room_id) or {}
            contributions = room.get("contributions") or {}
            self._rooms[room_id] = {
                "enabled": bool(room.get("enabled", True)),
                "contributions": {
                    light: contributions[light]
                    for light in lights
                    if isinstance(contributions.get(light), dict)
                },
            }

    def enabled(self, room_id: str) -> bool:
        """The room's Automatic switch."""
        return self._rooms.get(room_id, {}).get("enabled", True)

    def set_enabled(self, room_id: str, enabled: bool) -> None:
        """Change the room's Automatic switch."""
        self._rooms.setdefault(room_id, {"contributions": {}})["enabled"] = enabled
        self._save()

    def contribution(self, room_id: str, light: str) -> Contribution:
        """A light's contribution (empty if never learned)."""
        raw = self._rooms.get(room_id, {}).get("contributions", {}).get(light)
        if not raw:
            return Contribution()
        value = raw.get("value")
        return Contribution(
            value=value
            if isinstance(value, int | float) and not isinstance(value, bool)
            else None,
            samples=int(raw.get("samples") or 0),
            updated=raw.get("updated"),
        )

    def set_contribution(
        self, room_id: str, light: str, contribution: Contribution
    ) -> None:
        """Save a light's contribution."""
        room = self._rooms.setdefault(room_id, {"enabled": True, "contributions": {}})
        room["contributions"][light] = {
            "value": contribution.value,
            "samples": contribution.samples,
            "updated": contribution.updated,
        }
        self._save()

    @staticmethod
    def stamp(now: datetime) -> str:
        """ISO time of an update."""
        return now.isoformat()

    def _data(self) -> dict[str, Any]:
        return {"rooms": self._rooms}

    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        """Save now (unload)."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the file (entry removed)."""
        await self._store.async_remove()
