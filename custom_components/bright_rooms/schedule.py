"""Bands of a room: pure functions, no Home Assistant.

A band overrides some settings of its room while its conditions hold: a time
window of the day (on some days) and/or the light, bright or dark, of this
room or of another room of the entry. A time window is [start, end); one
whose end is not after its start crosses midnight, and its days are the days
it starts on. Without a time window, the days restrict by the current
weekday. The first active band in the list wins.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LIGHTS = ("bright", "dark")
MAX_BANDS = 8
# Number overrides with their limits (seconds).
NUMBER_OVERRIDES: dict[str, tuple[int, int]] = {
    "on_delay": (0, 600),
    "empty_wait": (0, 3600),
    "zone_wait": (0, 3600),
}
OVERRIDES = (*NUMBER_OVERRIDES, "zone_sensors")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
_BINARY_SENSOR = re.compile(r"^binary_sensor\.[a-z0-9_]+$")

# Dark state of a room by id (None: this room); None when unknown.
DarkOf = Callable[[str | None], bool | None]


@dataclass(frozen=True, slots=True)
class Band:
    """A validated band."""

    id: str
    name: str | None
    start: int | None  # minutes after midnight; both or neither
    end: int | None
    days: frozenset[int]  # 0 = Monday; empty = every day
    light: str | None = None  # "bright" or "dark"
    light_room: str | None = None  # None: this room
    on_delay: int | None = None
    empty_wait: int | None = None
    zone_wait: int | None = None
    zone_sensors: tuple[str, ...] | None = None

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Band:
        """A band saved by `validate_schedule` (or by 0.1.4/0.1.5: time only)."""
        start, end = data.get("start"), data.get("end")
        zone = data.get("zone_sensors")
        return cls(
            id=data["id"],
            name=data.get("name"),
            start=_minutes(start) if start else None,
            end=_minutes(end) if end else None,
            days=frozenset(WEEKDAYS.index(d) for d in data.get("days") or ()),
            light=data.get("light"),
            light_room=data.get("light_room"),
            on_delay=data.get("on_delay"),
            empty_wait=data.get("empty_wait"),
            zone_wait=data.get("zone_wait"),
            zone_sensors=tuple(zone) if zone is not None else None,
        )

    @property
    def timed(self) -> bool:
        """Whether the band has a time window."""
        return self.start is not None and self.end is not None

    @property
    def label(self) -> str:
        """Its name, or a description: time range and/or light."""
        if self.name:
            return self.name
        parts = []
        if self.timed:
            parts.append(f"{_hhmm(self.start)}–{_hhmm(self.end)}")  # type: ignore[arg-type]
        if self.light:
            parts.append(self.light)
        return " · ".join(parts)

    def active(self, now: datetime, dark_of: DarkOf | None = None) -> bool:
        """Whether every condition of the band holds at this local time."""
        if self.light is not None:
            dark = dark_of(self.light_room) if dark_of else None
            if dark is None or dark != (self.light == "dark"):
                return False
        today = now.weekday()

        def on(day: int) -> bool:
            return not self.days or day in self.days

        if not self.timed:
            return on(today)
        start, end = self.start, self.end
        minute = now.hour * 60 + now.minute
        if start < end:  # type: ignore[operator]
            return start <= minute < end and on(today)  # type: ignore[operator]
        # Crosses midnight: the evening part today, the morning part from yesterday.
        return (minute >= start and on(today)) or (  # type: ignore[operator]
            minute < end and on((today - 1) % 7)  # type: ignore[operator]
        )


def _minutes(value: str) -> int:
    match = _TIME.match(value)
    if match is None:
        raise ValueError(value)
    return int(match.group(1)) * 60 + int(match.group(2))


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def active_band(
    bands: Iterable[Band], now: datetime, dark_of: DarkOf | None = None
) -> Band | None:
    """The first band active at this local time, if any."""
    return next((band for band in bands if band.active(now, dark_of)), None)


def next_boundary(bands: Sequence[Band], now: datetime) -> datetime | None:
    """The next local time a time window starts or ends, or a day begins.

    Bands that depend on the weekday change at midnight too.
    """
    times = []
    base = now.replace(second=0, microsecond=0)
    for band in bands:
        minutes: list[int] = []
        if band.timed:
            minutes += [band.start, band.end]  # type: ignore[list-item]
        if band.days:
            minutes.append(0)
        for minute in minutes:
            at = base.replace(hour=minute // 60, minute=minute % 60)
            if at <= now:
                at += timedelta(days=1)
            times.append(at)
    return min(times) if times else None


def validate_schedule(
    raw: Any, room_ids: Iterable[str] = ()
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The bands to save, and errors.

    `room_ids`: the rooms a light condition may refer to (this room included
    when it already exists; null always means this room). Errors:
    `{"schedule": "schedule_invalid"}` for anything wrong, plus
    `"schedule.<index>": "schedule_invalid"` for each band that is wrong.
    """
    invalid = {"schedule": "schedule_invalid"}
    if raw is None:
        return [], {}
    if not isinstance(raw, list) or len(raw) > MAX_BANDS:
        return [], invalid
    rooms = set(room_ids)
    bands: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    used: set[str] = set()
    for i, item in enumerate(raw):
        band = _band(item, used, rooms)
        if band is None:
            errors[f"schedule.{i}"] = "schedule_invalid"
            continue
        used.add(band["id"])
        bands.append(band)
    if errors:
        return [], {**invalid, **errors}
    return bands, {}


def _empty(value: Any) -> bool:
    return value is None or value == ""


def _band(item: Any, used: set[str], rooms: set[str]) -> dict[str, Any] | None:
    """One band, normalized, or None if invalid."""
    if not isinstance(item, dict):
        return None
    start, end = item.get("start"), item.get("end")
    if _empty(start) != _empty(end):
        return None  # both or neither
    try:
        start = None if _empty(start) else _hhmm(_minutes(str(start)))
        end = None if _empty(end) else _hhmm(_minutes(str(end)))
    except ValueError:
        return None
    days = item.get("days") or []
    if not isinstance(days, list) or any(d not in WEEKDAYS for d in days):
        return None
    name = item.get("name")
    if name is not None and not isinstance(name, str):
        return None
    light = None if _empty(item.get("light")) else item.get("light")
    if light is not None and light not in LIGHTS:
        return None
    light_room = None if _empty(item.get("light_room")) else item.get("light_room")
    if light_room is not None and light_room not in rooms:
        return None
    if start is None and light is None:
        return None  # no condition
    band: dict[str, Any] = {
        "id": "",
        "name": (name or "").strip() or None,
        "start": start,
        "end": end,
        "days": [d for d in WEEKDAYS if d in days],
        "light": light,
        "light_room": light_room if light is not None else None,
    }
    for key, (low, high) in NUMBER_OVERRIDES.items():
        value = item.get(key)
        if _empty(value):
            band[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        if not float(value).is_integer() or not low <= value <= high:
            return None
        band[key] = int(value)
    zone = item.get("zone_sensors")
    if zone is not None:
        if not isinstance(zone, list) or not all(
            isinstance(e, str) and _BINARY_SENSOR.match(e) for e in zone
        ):
            return None
        zone = list(dict.fromkeys(zone))
    band["zone_sensors"] = zone
    if all(band[key] is None for key in OVERRIDES):
        return None  # no override
    band_id = item.get("id")
    if not isinstance(band_id, str) or not band_id or band_id in used:
        band_id = uuid.uuid4().hex
    band["id"] = band_id
    return band
