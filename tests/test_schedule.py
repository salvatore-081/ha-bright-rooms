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
        "light": None,
        "light_room": None,
        "on_delay": None,
        "empty_wait": 120,
        "zone_wait": None,
        "zone_sensors": None,
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


def _dark(value):
    return lambda room_id: value


def test_light_band() -> None:
    band = Band.from_data({"id": "l", "light": "bright", "on_delay": 120})
    assert not band.timed
    assert band.active(_at(0, 12), _dark(False))
    assert not band.active(_at(0, 12), _dark(True))
    assert not band.active(_at(0, 12), _dark(None))  # unknown: not met
    assert not band.active(_at(0, 12))  # no light known at all
    dark = Band.from_data({"id": "d", "light": "dark", "empty_wait": 5})
    assert dark.active(_at(0, 12), _dark(True))
    assert not dark.active(_at(0, 12), _dark(False))


def test_light_band_of_another_room() -> None:
    band = Band.from_data(
        {"id": "l", "light": "dark", "light_room": "living", "empty_wait": 5}
    )
    rooms = {"living": True, None: False}
    assert band.active(_at(0, 12), rooms.get)
    rooms["living"] = False
    assert not band.active(_at(0, 12), rooms.get)


def test_light_and_time_band() -> None:
    band = Band.from_data(
        {"id": "x", "start": "18:00", "end": "23:00", "light": "dark", "empty_wait": 5}
    )
    assert band.active(_at(0, 20), _dark(True))
    assert not band.active(_at(0, 20), _dark(False))
    assert not band.active(_at(0, 12), _dark(True))
    assert band.label == "18:00–23:00 · dark"
    assert (
        Band.from_data({"id": "y", "light": "bright", "on_delay": 1}).label == "bright"
    )


def test_days_without_a_time_window() -> None:
    band = Band.from_data(
        {"id": "w", "light": "bright", "days": ["sat", "sun"], "on_delay": 9}
    )
    assert not band.active(_at(0, 12), _dark(False))  # Friday
    assert band.active(_at(1, 12), _dark(False))  # Saturday
    # Weekday bands change at midnight.
    assert next_boundary([band], _at(0, 12)) == _at(1, 0)


def test_band_of_0_1_4_still_works() -> None:
    band = Band.from_data(
        {
            "id": "o",
            "name": None,
            "start": "22:00",
            "end": "06:00",
            "days": [],
            "empty_wait": 600,
            "zone_wait": None,
        }
    )
    assert band.active(_at(0, 23))
    assert (band.light, band.on_delay, band.zone_sensors) == (None, None, None)


def test_validate_light_bands() -> None:
    bands, errors = validate_schedule(
        [
            {"light": "dark", "light_room": "living", "empty_wait": 300},
            {"light": "bright", "light_room": "", "on_delay": 120.0},
            {"start": "18:00", "end": "23:00", "light": "", "zone_sensors": []},
            {
                "start": "06:00",
                "end": "08:00",
                "zone_sensors": ["binary_sensor.hall", "binary_sensor.hall"],
                "light_room": "living",  # dropped without a light condition
            },
        ],
        ["kitchen", "living"],
    )
    assert errors == {}
    assert bands[0]["light"] == "dark" and bands[0]["light_room"] == "living"
    assert bands[0]["start"] is None and bands[0]["end"] is None
    assert bands[1]["light_room"] is None and bands[1]["on_delay"] == 120
    assert bands[2]["light"] is None and bands[2]["zone_sensors"] == []
    assert bands[3]["zone_sensors"] == ["binary_sensor.hall"]
    assert bands[3]["light_room"] is None


def test_validate_light_band_errors() -> None:
    rooms = ["kitchen"]
    for bad in (
        {"light": "dusk", "empty_wait": 5},
        {"light": "dark", "light_room": "gone", "empty_wait": 5},
        {"days": ["mon"], "empty_wait": 5},  # no condition
        {"start": "06:00", "empty_wait": 5},  # start without end
        {"end": "06:00", "light": "dark", "empty_wait": 5},
        {"light": "dark"},  # no override
        {"light": "dark", "on_delay": 601},
        {"light": "dark", "zone_sensors": ["sensor.hall"]},
        {"light": "dark", "zone_sensors": "binary_sensor.hall"},
        {"light": "dark", "zone_sensors": [3]},
    ):
        assert validate_schedule([bad], rooms) == (
            [],
            {"schedule": "schedule_invalid", "schedule.0": "schedule_invalid"},
        ), bad
