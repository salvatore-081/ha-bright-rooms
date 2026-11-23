"""Tests of the time bands (pure functions)."""

from __future__ import annotations

from datetime import datetime

from custom_components.bright_rooms.schedule import (
    MAX_BANDS,
    Band,
    active_band,
    next_boundary,
    validate_schedule,
)

# 2026-01-16 is a Friday.
FRI = datetime(2026, 1, 16)


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    return FRI.replace(day=16 + day_offset, hour=hour, minute=minute)


def _band(**kw) -> Band:
    data = {"id": "b", "start": "22:00", "end": "06:00", "days": [], "empty_wait": 60}
    return Band.from_data({**data, **kw})


def test_band_crossing_midnight_with_days() -> None:
    band = _band(days=["fri"])
    assert band.active(_at(0, 23))  # Friday evening
    assert band.active(_at(1, 5, 59))  # Saturday morning: started on Friday
    assert not band.active(_at(1, 6))  # end excluded
    assert not band.active(_at(1, 23))  # Saturday evening
    assert not band.active(_at(0, 5))  # Friday morning: started on Thursday
    assert not band.active(_at(0, 21, 59))


def test_band_within_a_day() -> None:
    band = _band(start="08:00", end="12:30", days=["mon", "fri"])
    assert band.active(_at(0, 8))
    assert band.active(_at(0, 12, 29))
    assert not band.active(_at(0, 12, 30))
    assert not band.active(_at(1, 9))  # Saturday
    every_day = _band(start="08:00", end="12:30")
    assert every_day.active(_at(1, 9))


def test_band_whole_day() -> None:
    band = _band(start="07:00", end="07:00", days=["fri"])
    assert band.active(_at(0, 7))
    assert band.active(_at(1, 6, 59))
    assert not band.active(_at(1, 7))


def test_first_active_band_wins() -> None:
    a = _band(id="a", start="18:00", end="23:00")
    b = _band(id="b", start="20:00", end="21:00")
    assert active_band([b, a], _at(0, 20, 30)).id == "b"
    assert active_band([a, b], _at(0, 20, 30)).id == "a"
    assert active_band([a, b], _at(0, 17)) is None


def test_label() -> None:
    assert _band(name="Dinner").label == "Dinner"
    assert _band(start="7:05", end="09:00").label == "07:05–09:00"


def test_next_boundary() -> None:
    bands = [_band(start="18:00", end="23:00")]
    assert next_boundary(bands, _at(0, 17, 30)) == _at(0, 18)
    assert next_boundary(bands, _at(0, 18)) == _at(0, 23)
    assert next_boundary(bands, _at(0, 23, 30)) == _at(1, 18)
    assert next_boundary([], _at(0, 12)) is None


def test_validate_normalizes() -> None:
    bands, errors = validate_schedule(
        [
            {
                "id": "keep",
                "name": "  Dinner ",
                "start": "18:00:00",
                "end": "7:30",
                "days": ["sun", "mon", "mon"],
                "empty_wait": 120.0,
                "zone_wait": None,
            },
            {"name": " ", "start": "06:00", "end": "08:00", "zone_wait": 0},
            {"id": "keep", "start": "09:00", "end": "10:00", "empty_wait": 5},
        ]
    )
    assert errors == {}
    first, second, third = bands
    assert first == {
        "id": "keep",
        "name": "Dinner",
        "start": "18:00",
        "end": "07:30",
        "days": ["mon", "sun"],
        "empty_wait": 120,
        "zone_wait": None,
    }
    assert isinstance(first["empty_wait"], int)
    assert second["name"] is None and second["days"] == []
    assert len(second["id"]) == 32 and second["zone_wait"] == 0
    assert third["id"] not in ("keep", second["id"])  # a repeated id is replaced
    assert validate_schedule(None) == ([], {})
    assert validate_schedule([]) == ([], {})


def test_validate_errors() -> None:
    good = {"start": "06:00", "end": "08:00", "empty_wait": 60}
    for bad in (
        {**good, "start": "24:00"},
        {**good, "end": "8"},
        {**good, "start": None},
        {**good, "days": ["monday"]},
        {**good, "days": "mon"},
        {**good, "empty_wait": 3601},
        {**good, "empty_wait": -1},
        {**good, "empty_wait": 1.5},
        {**good, "empty_wait": True},
        {**good, "empty_wait": "60"},
        {**good, "empty_wait": None},  # no override at all
        {**good, "name": 3},
        "06:00-08:00",
    ):
        bands, errors = validate_schedule([good, bad])
        assert bands == []
        assert errors == {
            "schedule": "schedule_invalid",
            "schedule.1": "schedule_invalid",
        }, bad
    assert validate_schedule([good] * (MAX_BANDS + 1)) == (
        [],
        {"schedule": "schedule_invalid"},
    )
    assert validate_schedule({"start": "06:00"}) == (
        [],
        {"schedule": "schedule_invalid"},
    )
