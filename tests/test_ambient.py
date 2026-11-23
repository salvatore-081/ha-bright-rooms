"""Tests of the pure functions: ambient light, darkness, curve, measurements."""

from __future__ import annotations

import pytest

from custom_components.bright_rooms.ambient import (
    LightReading,
    Member,
    Rejection,
    ambient_light,
    brightness_pct,
    light_fraction,
    measure_group,
    must_hold,
    next_dark,
    own_light,
    parse_lux,
)

ON = LightReading(available=True, on=True, fraction=1.0, contribution=100)
HALF = LightReading(available=True, on=True, fraction=0.5, contribution=60)
OFF = LightReading(available=True, on=False, fraction=1.0, contribution=None)
UNKNOWN = LightReading(available=True, on=True, fraction=1.0, contribution=None)
GONE = LightReading(available=False, on=False, fraction=1.0, contribution=10)


def test_parse_lux() -> None:
    assert parse_lux("12.5") == 12.5
    assert parse_lux("unavailable") is None
    assert parse_lux("nan") is None
    assert parse_lux(None) is None


def test_light_fraction() -> None:
    assert light_fraction(255, True) == 1
    assert light_fraction(51, True) == 0.2
    assert light_fraction(None, True) == 1
    assert light_fraction(51, False) == 1


def test_own_light_and_hold() -> None:
    assert own_light([ON, HALF, OFF]) == 130
    assert own_light([ON, UNKNOWN]) is None
    assert own_light([OFF, GONE]) == 0
    assert not must_hold([ON, OFF])
    assert must_hold([ON, UNKNOWN])
    assert must_hold([GONE])


def test_ambient_light() -> None:
    assert ambient_light(150.4, 100) == 50
    assert ambient_light(80, 100) == 0
    assert ambient_light(None, 0) is None
    assert ambient_light(10, None) is None


@pytest.mark.parametrize(
    ("previous", "ambient", "expected"),
    [
        (None, 39, True),
        (None, 81, False),
        (None, 50, True),  # below the midpoint (60)
        (None, 70, False),
        (True, 70, True),
        (False, 50, False),
        (False, 39, True),
        (True, 81, False),
        (True, 40, True),
        (False, 80, False),
        (True, None, None),
    ],
)
def test_next_dark(previous, ambient, expected) -> None:
    assert next_dark(previous, ambient, 40, 80) is expected


@pytest.mark.parametrize(
    ("ambient", "expected"),
    [(None, 100), (0, 20), (10, 20), (105, 60), (200, 100), (500, 100)],
)
def test_brightness_pct(ambient, expected) -> None:
    assert brightness_pct(ambient, 20, 10, 200) == expected


def _group(*members: Member, **kw):
    args = {
        "turned_on": True,
        "before": 10.0,
        "after": 110.0,
        "others": 0.0,
        "members": members or (Member(1.0, None),),
        "ambient_max": 60,
        "weight": 0.2,
    }
    return measure_group(**{**args, **kw})


def test_single_light() -> None:
    assert _group() == [100]
    assert _group(turned_on=False, before=110.0, after=10.0) == [100]
    assert _group(Member(0.5, None), after=60.0) == [100]
    assert _group(Member(0.502, None), after=60.0) == [100]  # 99.6 rounded
    # Other lights on: the ambient light is without them.
    assert _group(before=110.0, after=210.0, others=100.0) == [100]
    # A known value moves by the weight: 100 x 0.8 + 80 x 0.2.
    assert _group(Member(1.0, 100), after=90.0) == [96]
    assert _group(Member(1.0, 300), after=110.0) == [260]
    assert _group(Member(1.0, 34), after=110.0) == [47]


def test_single_light_rejections() -> None:
    assert _group(after=None) is Rejection.NO_READING
    assert _group(others=None) is Rejection.NO_READING
    assert _group(before=70.0, after=170.0) is Rejection.TOO_BRIGHT
    # Turning off: the ambient light after counts.
    assert _group(turned_on=False, before=170.0, after=70.0) is Rejection.TOO_BRIGHT
    assert _group(after=14.0) is Rejection.TOO_SMALL
    assert _group(after=5.0) is Rejection.TOO_SMALL
    # The jump as measured must be 5 lx, before normalizing.
    assert _group(Member(0.2, None), after=14.0) is Rejection.TOO_SMALL
    assert _group(Member(1.0, 30)) is Rejection.OUT_OF_RANGE
    assert _group(Member(1.0, 301)) is Rejection.OUT_OF_RANGE
    assert _group(Member(1.0, 0)) is Rejection.OUT_OF_RANGE


def test_group_all_known() -> None:
    # Expected 100 x 1 + 50 x 0.5 = 125, jump 250: factor 2, each moves 20 % of the way.
    result = _group(Member(1.0, 100), Member(0.5, 50), after=260.0)
    assert result == [120, 60]
    assert _group(Member(1.0, 100), Member(1.0, 50), after=10.0 + 450 + 1) is (
        Rejection.OUT_OF_RANGE
    )
    assert _group(Member(1.0, 100), Member(1.0, 50), after=10.0 + 49) is (
        Rejection.OUT_OF_RANGE
    )


def test_group_one_unknown() -> None:
    # 130 lx jump, 100 explained by the known light: 30 for the other one at half.
    assert _group(Member(1.0, 100), Member(0.5, None), after=140.0) == [None, 60]
    # What is left is too little.
    assert _group(Member(1.0, 100), Member(1.0, None), after=114.0) is (
        Rejection.TOO_SMALL
    )


def test_group_two_unknown() -> None:
    assert _group(Member(1.0, None), Member(1.0, None)) is Rejection.TOO_MANY_UNKNOWN
