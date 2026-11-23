"""Time bands of a room: pure functions, no Home Assistant.

A band overrides some waits of its room between two times of the day, on
some days. It is active when the local time is in [start, end); a band whose
end is not after its start crosses midnight, and its days are the days it
starts on. The first active band in the list wins.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_BANDS = 8
# Band fields that override the room's own value, with their limits (seconds).
OVERRIDES: dict[str, tuple[int, int]] = {
    "empty_wait": (0, 3600),
    "zone_wait": (0, 3600),
}
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")


@dataclass(frozen=True, slots=True)
class Band:
    """A validated band."""

    id: str
    name: str | None
    start: int  # minutes after midnight
    end: int
    days: frozenset[int]  # 0 = Monday; empty = every day
    empty_wait: int | None = None
    zone_wait: int | None = None

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Band:
        """A band saved by `validate_schedule`."""
        return cls(
            id=data["id"],
            name=data.get("name"),
            start=_minutes(data["start"]),
            end=_minutes(data["end"]),
            days=frozenset(WEEKDAYS.index(d) for d in data.get("days") or ()),
            empty_wait=data.get("empty_wait"),
            zone_wait=data.get("zone_wait"),
        )

    @property
    def label(self) -> str:
        """Its name, or its time range."""
        return self.name or f"{_hhmm(self.start)}–{_hhmm(self.end)}"

    def active(self, now: datetime) -> bool:
        """Whether the band applies at this local time."""
        minute = now.hour * 60 + now.minute
        today = now.weekday()

        def on(day: int) -> bool:
            return not self.days or day in self.days

        if self.start < self.end:
            return self.start <= minute < self.end and on(today)
        # Crosses midnight: the evening part today, the morning part from yesterday.
        return (minute >= self.start and on(today)) or (
            minute < self.end and on((today - 1) % 7)
        )


def _minutes(value: str) -> int:
    match = _TIME.match(value)
    if match is None:
        raise ValueError(value)
    return int(match.group(1)) * 60 + int(match.group(2))


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def active_band(bands: Iterable[Band], now: datetime) -> Band | None:
    """The first band active at this local time, if any."""
    return next((band for band in bands if band.active(now)), None)


def next_boundary(bands: Sequence[Band], now: datetime) -> datetime | None:
    """The next local time a band starts or ends (to refresh the room's state)."""
    if not bands:
        return None
    base = now.replace(second=0, microsecond=0)
    times = []
    for band in bands:
        for minute in (band.start, band.end):
            at = base.replace(hour=minute // 60, minute=minute % 60)
            if at <= now:
                at += timedelta(days=1)
            times.append(at)
    return min(times)


def validate_schedule(raw: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The bands to save, and errors.

    Errors: `{"schedule": "schedule_invalid"}` for anything wrong, plus
    `"schedule.<index>": "schedule_invalid"` for each band that is wrong.
    """
    invalid = {"schedule": "schedule_invalid"}
    if raw is None:
        return [], {}
    if not isinstance(raw, list) or len(raw) > MAX_BANDS:
        return [], invalid
    bands: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    used: set[str] = set()
    for i, item in enumerate(raw):
        band = _band(item, used)
        if band is None:
            errors[f"schedule.{i}"] = "schedule_invalid"
            continue
        used.add(band["id"])
        bands.append(band)
    if errors:
        return [], {**invalid, **errors}
    return bands, {}


def _band(item: Any, used: set[str]) -> dict[str, Any] | None:
    """One band, normalized, or None if invalid."""
    if not isinstance(item, dict):
        return None
    try:
        start = _hhmm(_minutes(str(item["start"])))
        end = _hhmm(_minutes(str(item["end"])))
    except KeyError, ValueError:
        return None
    days = item.get("days") or []
    if not isinstance(days, list) or any(d not in WEEKDAYS for d in days):
        return None
    name = item.get("name")
    if name is not None and not isinstance(name, str):
        return None
    band: dict[str, Any] = {
        "id": "",
        "name": (name or "").strip() or None,
        "start": start,
        "end": end,
        "days": [d for d in WEEKDAYS if d in days],
    }
    for key, (low, high) in OVERRIDES.items():
        value = item.get(key)
        if value is None or value == "":
            band[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        if not float(value).is_integer() or not low <= value <= high:
            return None
        band[key] = int(value)
    if all(band[key] is None for key in OVERRIDES):
        return None
    band_id = item.get("id")
    if not isinstance(band_id, str) or not band_id or band_id in used:
        band_id = uuid.uuid4().hex
    band["id"] = band_id
    return band
