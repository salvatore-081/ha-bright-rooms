"""Ambient light, darkness and contribution measurements: pure functions.

Nothing here knows about Home Assistant: the engine feeds plain values in.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .const import LEARN_MIN_JUMP


@dataclass(frozen=True, slots=True)
class LightReading:
    """A room light as the ambient light computation sees it."""

    available: bool
    on: bool
    fraction: float  # brightness / 255 for dimmable lights, 1 for on/off lights
    contribution: float | None  # lux at full brightness, None until learned


def parse_lux(value: str | None) -> float | None:
    """The reading of an illuminance sensor, None if it is not a number."""
    if value is None:
        return None
    try:
        lux = float(value)
    except ValueError:
        return None
    return lux if math.isfinite(lux) else None


def light_fraction(brightness: int | None, dimmable: bool) -> float:
    """Share of the full light output of a light that is on."""
    if not dimmable or brightness is None:
        return 1.0
    return max(0.0, min(255, brightness)) / 255


def own_light(lights: Iterable[LightReading]) -> float | None:
    """Lux the room's own lights add, None if one that is on is not learned yet."""
    total = 0.0
    for light in lights:
        if not light.available or not light.on:
            continue
        if light.contribution is None:
            return None
        total += light.contribution * light.fraction
    return total


def must_hold(lights: Iterable[LightReading]) -> bool:
    """The ambient light cannot be computed now: keep the previous value."""
    return any(
        not light.available or (light.on and light.contribution is None)
        for light in lights
    )


def ambient_light(raw: float | None, own: float | None) -> int | None:
    """Raw lux without the room's own lights, rounded; None without a reading."""
    if raw is None or own is None:
        return None
    return max(0, round(raw - own))


def next_dark(
    previous: bool | None, ambient: int | None, dark_below: float, bright_above: float
) -> bool | None:
    """Darkness with hysteresis between `dark_below` and `bright_above`."""
    if ambient is None:
        return None
    if ambient < dark_below:
        return True
    if ambient > bright_above:
        return False
    if previous is not None:
        return previous
    return ambient < (dark_below + bright_above) / 2


def brightness_pct(
    ambient: int | None, minimum: float, dark_lux: float, full_lux: float
) -> int:
    """Brightness of dimmable lights for this ambient light.

    `minimum` % at or below `dark_lux`, 100 % at or above `full_lux`, linear in
    between; 100 % without a reading.
    """
    if ambient is None or ambient >= full_lux or full_lux <= dark_lux:
        return 100
    if ambient <= dark_lux:
        return round(minimum)
    share = (ambient - dark_lux) / (full_lux - dark_lux)
    return round(minimum + (100 - minimum) * share)


class Rejection(StrEnum):
    """Why a contribution measurement was discarded."""

    NO_READING = "no_reading"
    TOO_BRIGHT = "too_bright"
    LIGHT_CHANGED = "light_changed"
    OTHER_LIGHT_CHANGED = "other_light_changed"
    TOO_SMALL = "too_small"
    OUT_OF_RANGE = "out_of_range"
    TOO_MANY_UNKNOWN = "too_many_unknown"


@dataclass(frozen=True, slots=True)
class Member:
    """A light of a measured group: its brightness fraction and its value."""

    fraction: float  # while on: after turning on, before turning off
    value: float | None  # current contribution, None if unknown


def measure_group(
    *,
    turned_on: bool,
    before: float | None,
    after: float | None,
    others: float | None,
    members: Sequence[Member],
    ambient_max: float,
    weight: float,
) -> list[int | None] | Rejection:
    """New contributions of a group of lights switched together, or why not.

    `before` and `after` are the raw readings at the first change and after
    the settling time; `others` the lux of the room lights outside the group
    (unchanged during the measurement; None if one of them is on and not
    learned). The ambient light that must be low is the one without the
    group: before when it turns on, after when it turns off. The jump must be
    at least LEARN_MIN_JUMP lx as measured.

    - Every value known: the jump is compared with the expected one
      (sum of value x fraction); the factor must be between 1/3 and 3 and each
      value moves towards value x factor by `weight`.
    - Exactly one unknown: it gets what the known ones do not explain,
      normalized by its fraction, if that is at least LEARN_MIN_JUMP lx; the
      known values stay as they are.
    - More unknown: discarded.

    The result has one entry per member: the new value, or None if unchanged.
    A group of one light is the measurement of that light alone.
    """
    if before is None or after is None or others is None:
        return Rejection.NO_READING
    ambient = ambient_light(before if turned_on else after, others)
    if ambient is None:
        return Rejection.NO_READING
    if ambient > ambient_max:
        return Rejection.TOO_BRIGHT
    jump = after - before if turned_on else before - after
    if jump < LEARN_MIN_JUMP or any(m.fraction <= 0 for m in members):
        return Rejection.TOO_SMALL
    unknown = [i for i, m in enumerate(members) if m.value is None]
    if len(unknown) > 1:
        return Rejection.TOO_MANY_UNKNOWN
    known = sum(m.value * m.fraction for m in members if m.value is not None)
    if unknown:
        (u,) = unknown
        value = (jump - known) / members[u].fraction
        if value < LEARN_MIN_JUMP:
            return Rejection.TOO_SMALL
        return [round(value) if i == u else None for i in range(len(members))]
    if known <= 0:
        return Rejection.OUT_OF_RANGE
    factor = jump / known
    if not 1 / 3 <= factor <= 3:
        return Rejection.OUT_OF_RANGE
    return [
        round(m.value * (1 - weight) + m.value * factor * weight)  # type: ignore[operator]
        for m in members
    ]
