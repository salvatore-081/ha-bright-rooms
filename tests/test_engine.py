"""Engine tests: turning on, turning off, daylight, holds and learning."""

from __future__ import annotations

from types import MappingProxyType

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar

from custom_components.bright_rooms.const import (
    CONF_BRIGHTNESS_MIN,
    CONF_MIN_OFF_SECONDS,
    CONF_ON_DELAY,
    CONF_ONLY_WHEN_DARK,
    CONF_OTHER_LIGHTS,
    ROOM_DEFAULTS,
)
from custom_components.bright_rooms.engine import RoomConfig

from .helpers import (
    CEILING,
    LUX,
    OTHER,
    PRESENCE,
    STRIP,
    ZONE,
    advance,
    kitchen,
    lux,
    make,
    presence,
    set_light,
    settle,
)


def _last(room) -> tuple[str, str] | None:
    a = room.last_action
    return (a.action.value, a.reason.value) if a else None


def _learn(entry, light: str, value: float | None) -> None:
    room = kitchen(entry)
    entry.runtime_data.set_contribution(room.subentry_id, light, value)


async def _lights_on(hass: HomeAssistant, freezer: FrozenDateTimeFactory, **room):
    """Set up, someone walks in, the lights go on."""
    entry, lights = await make(hass, freezer, **room)
    await presence(hass, True)
    await settle(hass)
    assert hass.states.get(CEILING).state == "on"
    lights.clear()
    return entry, lights


# ------------------------------------------------------------------ turn on


async def test_turns_on_with_presence_in_the_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    room = kitchen(entry)
    assert room.dark is True and room.status == "off"
    await presence(hass, True)
    await settle(hass)
    calls = {tuple(c.data["entity_id"]): dict(c.data) for c in lights.of("turn_on")}
    # On/off lights without data, dimmable lights with the curve's brightness.
    assert calls == {
        (STRIP,): {"entity_id": [STRIP]},
        (CEILING,): {"entity_id": [CEILING], "brightness_pct": 100},
    }
    assert room.status == "on"
    assert _last(room) == ("turned_on", "presence_dark")


async def test_not_when_bright(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lux="500")
    room = kitchen(entry)
    assert room.dark is False
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    assert _last(room) == ("skipped_on", "not_dark")


async def test_hysteresis(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry, _ = await make(hass, freezer, lux="70")
    room = kitchen(entry)
    assert room.dark is False  # first value: above the midpoint (60)
    await lux(hass, 39)
    assert room.dark is True
    await lux(hass, 79)
    assert room.dark is True  # between the thresholds: unchanged
    await lux(hass, 81)
    assert room.dark is False
    await lux(hass, 41)
    assert room.dark is False


async def test_always_and_brightness_curve(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(
        hass,
        freezer,
        lux="105",
        **{CONF_ONLY_WHEN_DARK: False, CONF_BRIGHTNESS_MIN: 20},
    )
    await presence(hass, True)
    await settle(hass)
    (dimmed,) = [c for c in lights.of("turn_on") if c.data["entity_id"] == [CEILING]]
    # 20 % at 10 lx, 100 % at 200 lx: 60 % at 105 lx.
    assert dimmed.data["brightness_pct"] == 60
    assert _last(kitchen(entry)) == ("turned_on", "presence_always")


async def test_no_reading_counts_as_dark_full_brightness(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lux=None, **{CONF_BRIGHTNESS_MIN: 20})
    room = kitchen(entry)
    assert room.ambient is None and room.dark is None
    await presence(hass, True)
    await settle(hass)
    (dimmed,) = [c for c in lights.of("turn_on") if c.data["entity_id"] == [CEILING]]
    assert dimmed.data["brightness_pct"] == 100


async def test_on_delay(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    _entry, lights = await make(hass, freezer, **{CONF_ON_DELAY: 20})
    await presence(hass, True)
    await advance(hass, freezer, 10)
    await presence(hass, False)  # not continuous: starts again
    await presence(hass, True)
    await advance(hass, freezer, 19)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_min_off_seconds(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await make(hass, freezer, **{CONF_MIN_OFF_SECONDS: 30})
    set_light(hass, CEILING, "on")
    set_light(hass, CEILING, "off")  # switched a moment ago
    await presence(hass, True)
    assert lights.calls == []
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_light_already_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Found on at startup; someone comes in during the startup grace."""
    set_light(hass, STRIP, "on")
    entry, lights = await make(hass, freezer)
    await advance(hass, freezer, 5)
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    assert _last(kitchen(entry)) == ("skipped_on", "lights_already_on")


async def test_unavailable_light_skipped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await make(hass, freezer)
    hass.states.async_set(STRIP, "unavailable")
    await presence(hass, True)
    await settle(hass)
    assert [c.data["entity_id"] for c in lights.calls] == [[CEILING]]


async def test_manual_off_while_occupied_not_lit_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    set_light(hass, CEILING, "off")
    set_light(hass, STRIP, "off")
    await advance(hass, freezer, 300, step=30)
    await lux(hass, 5)
    await settle(hass)
    assert lights.calls == []
    assert kitchen(entry).status == "off"
    # Next time someone comes in, the lights go on again.
    await presence(hass, False)
    await presence(hass, True)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


# ------------------------------------------------------------- dusk


async def _seated_in_daylight(hass, freezer, options=None, **room):
    """Someone sits down while it is bright: the lights stay off."""
    entry, lights = await make(hass, freezer, lux="500", options=options, **room)
    await presence(hass, True)
    await advance(hass, freezer, room.get(CONF_ON_DELAY, 0) + 1)
    await settle(hass)
    assert lights.calls == []
    assert _last(kitchen(entry)) == ("skipped_on", "not_dark")
    return entry, lights


async def test_turns_on_when_it_becomes_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _seated_in_daylight(
        hass, freezer, **{CONF_BRIGHTNESS_MIN: 20, CONF_ON_DELAY: 60}
    )
    await advance(hass, freezer, 600, step=60)
    await lux(hass, 30)  # dusk: dark now, no on_delay (already occupied)
    await settle(hass)
    calls = {tuple(c.data["entity_id"]): dict(c.data) for c in lights.of("turn_on")}
    # 20 % at 10 lx, 100 % at 200 lx: 28 % at 30 lx.
    assert calls == {
        (STRIP,): {"entity_id": [STRIP]},
        (CEILING,): {"entity_id": [CEILING], "brightness_pct": 28},
    }
    assert _last(kitchen(entry)) == ("turned_on", "became_dark")


async def test_not_lit_again_at_dusk_after_manual_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _seated_in_daylight(hass, freezer)
    await lux(hass, 30)
    await settle(hass)
    lights.clear()
    set_light(hass, CEILING, "off")
    set_light(hass, STRIP, "off")
    for value in (20, 35, 39, 25):  # still dark: no new transition
        await lux(hass, value)
        await advance(hass, freezer, 60, step=10)
    assert lights.calls == []


async def test_dusk_respects_min_off_seconds(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _seated_in_daylight(
        hass, freezer, options={"settle_seconds": 10}, **{CONF_MIN_OFF_SECONDS: 30}
    )
    set_light(hass, CEILING, "on")
    set_light(hass, CEILING, "off")
    await advance(hass, freezer, 10)  # the ambient light is no longer held
    await lux(hass, 30)
    assert lights.calls == []
    await advance(hass, freezer, 19)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2
    assert _last(kitchen(entry)) == ("turned_on", "became_dark")


async def test_dusk_not_when_empty(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await make(hass, freezer, lux="500")
    await lux(hass, 30)
    await settle(hass)
    assert lights.calls == []


async def test_dusk_not_when_a_light_is_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _seated_in_daylight(hass, freezer)
    set_light(hass, STRIP, "on")
    await lux(hass, 30)
    await settle(hass)
    assert lights.calls == []


async def test_dusk_not_when_disabled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _seated_in_daylight(hass, freezer)
    kitchen(entry).set_enabled(False)
    await lux(hass, 30)
    await settle(hass)
    assert lights.calls == []


async def test_dusk_not_from_unknown(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """No reading, then a dark one: not a transition from bright."""
    entry, lights = await _seated_in_daylight(hass, freezer)
    hass.states.async_set(LUX, "unavailable")
    await hass.async_block_till_done()
    assert kitchen(entry).dark is None
    await lux(hass, 30)
    await settle(hass)
    assert lights.calls == []


async def test_dusk_option_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _seated_in_daylight(hass, freezer, on_when_dark=False)
    await lux(hass, 30)
    await settle(hass)
    assert lights.calls == []


async def test_dusk_ignored_without_only_when_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The lights went on at arrival; turned off by hand, they stay off at dusk."""
    entry, lights = await make(hass, freezer, lux="500", **{CONF_ONLY_WHEN_DARK: False})
    await presence(hass, True)
    await settle(hass)
    assert _last(kitchen(entry)) == ("turned_on", "presence_always")
    set_light(hass, CEILING, "off")
    set_light(hass, STRIP, "off")
    lights.clear()
    await lux(hass, 30)
    await settle(hass)
    assert lights.calls == []


async def test_room_saved_without_the_option_turns_on_at_dusk(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _lights = await make(hass, freezer, lux="500")
    room = kitchen(entry)
    data = dict(room.data)
    data.pop("on_when_dark")
    assert RoomConfig.from_data(data).on_when_dark is True


# ------------------------------------------------------------------ startup


async def test_never_acts_on_startup_states(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(PRESENCE, "on")
    _entry, lights = await make(hass, freezer)
    hass.states.async_set(PRESENCE, "on")
    await advance(hass, freezer, 120, step=10)
    assert lights.calls == []


async def test_presence_back_from_unavailable_is_not_an_arrival(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    hass.states.async_set(PRESENCE, "unavailable")
    await hass.async_block_till_done()
    assert kitchen(entry).occupied is None
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    await presence(hass, False)
    await presence(hass, True)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_empty_room_with_lights_on_at_startup_turns_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_light(hass, CEILING, "on")
    entry, lights = await make(hass, freezer)
    room = kitchen(entry)
    await advance(hass, freezer, 29)
    assert lights.calls == [] and room.status == "on"
    # Presence sensors available for 30 s: the normal sequence starts.
    await advance(hass, freezer, 1)
    assert room.status == "waiting"
    await advance(hass, freezer, 30)
    await settle(hass)
    assert room.status == "dimmed"
    await advance(hass, freezer, 10)
    await settle(hass)
    assert room.status == "off"
    assert _last(room) == ("turned_off", "empty")


async def test_startup_grace_waits_for_the_presence_sensors(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(PRESENCE, "unavailable")
    set_light(hass, CEILING, "on")
    entry, _lights = await make(hass, freezer)
    await advance(hass, freezer, 120, step=10)
    assert kitchen(entry).status == "on"
    await presence(hass, False)  # the sensor is ready: the grace starts now
    await advance(hass, freezer, 29)
    assert kitchen(entry).status == "on"
    await advance(hass, freezer, 1)
    assert kitchen(entry).status == "waiting"


async def test_startup_grace_restarts_when_a_sensor_drops(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_light(hass, CEILING, "on")
    entry, _ = await make(hass, freezer)
    await advance(hass, freezer, 20)
    hass.states.async_set(PRESENCE, "unavailable")
    await advance(hass, freezer, 20)
    await presence(hass, False)
    await advance(hass, freezer, 29)
    assert kitchen(entry).status == "on"
    await advance(hass, freezer, 1)
    assert kitchen(entry).status == "waiting"


async def test_startup_turn_off_skipped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Not when someone is there, nor after someone changed a light."""
    hass.states.async_set(PRESENCE, "on")
    set_light(hass, CEILING, "on")
    entry, lights = await make(hass, freezer)
    await advance(hass, freezer, 120, step=10)
    assert lights.calls == []
    assert kitchen(entry).status == "on"


async def test_change_by_hand_during_the_startup_grace(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """No startup turn-off, but the room is empty with a light on: the waits run."""
    set_light(hass, CEILING, "on")
    _entry, lights = await make(hass, freezer, dim_percent=100)
    await advance(hass, freezer, 10)
    set_light(hass, CEILING, "on", brightness=100)
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]


async def test_nothing_turned_on_at_startup(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(PRESENCE, "on")
    entry, lights = await make(hass, freezer)
    await advance(hass, freezer, 120, step=10)
    assert lights.calls == []
    assert kitchen(entry).status == "off"


async def test_unavailable_presence_does_not_turn_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    hass.states.async_set(PRESENCE, "unavailable")
    await hass.async_block_till_done()
    await advance(hass, freezer, 600, step=30)
    assert lights.calls == []
    # Known to be empty again with the lights on: the usual waits, then off.
    await presence(hass, False)
    await advance(hass, freezer, 40)
    await settle(hass)
    assert kitchen(entry).status == "off"


async def test_off_sequence_dims_then_turns_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    assert room.status == "waiting"
    assert room.deadline is not None
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    (dim,) = lights.calls
    # Only the dimmable light, to 30 % of its brightness; the strip is untouched.
    assert dict(dim.data) == {"entity_id": [CEILING], "brightness": 76, "transition": 2}
    assert room.status == "dimmed"
    assert _last(room) == ("dimmed", "empty")
    lights.clear()
    await advance(hass, freezer, 10)
    await settle(hass)
    calls = {tuple(c.data["entity_id"]): dict(c.data) for c in lights.of("turn_off")}
    assert calls == {
        (STRIP,): {"entity_id": [STRIP]},
        (CEILING,): {"entity_id": [CEILING], "transition": 3},
    }
    assert room.status == "off"
    assert room.deadline is None
    assert _last(room) == ("turned_off", "empty")


async def test_off_sequence_without_dimming(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _lights_on(hass, freezer, dim_percent=100)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert lights.of("turn_on") == []
    assert len(lights.of("turn_off")) == 2


async def test_also_turns_off_lights_turned_on_by_hand(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(PRESENCE, "on")
    _entry, lights = await make(hass, freezer)
    set_light(hass, STRIP, "on")
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert [c.data["entity_id"] for c in lights.of("turn_off")] == [[STRIP]]


async def test_zone_extends_the_wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    hass.states.async_set(ZONE, "on")
    await presence(hass, False)
    assert room.status == "waiting"
    await advance(hass, freezer, 60, step=5)
    hass.states.async_set(ZONE, "off")
    await hass.async_block_till_done()
    # The empty wait starts when the zone is empty.
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.calls) == 1  # dimmed
    await advance(hass, freezer, 10)
    await settle(hass)
    assert _last(room) == ("turned_off", "empty")


async def test_zone_wait_has_a_limit(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    hass.states.async_set(ZONE, "on")
    await presence(hass, False)
    await advance(hass, freezer, 150, step=5)
    assert lights.calls == []
    # Back to the zone after the limit: no longer waited for.
    hass.states.async_set(ZONE, "off")
    hass.states.async_set(ZONE, "on")
    await advance(hass, freezer, 30)
    await settle(hass)
    assert room.status == "dimmed"
    await advance(hass, freezer, 10)
    await settle(hass)
    assert room.status == "off"
    assert _last(room) == ("turned_off", "zone_timeout")


async def test_zone_occupied_again_during_empty_wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    await presence(hass, False)
    await advance(hass, freezer, 20)
    hass.states.async_set(ZONE, "on")
    await advance(hass, freezer, 60, step=5)
    assert lights.calls == []
    hass.states.async_set(ZONE, "off")
    await advance(hass, freezer, 30)
    await settle(hass)
    assert kitchen(entry).status == "dimmed"


async def test_presence_back_while_dimmed_restores(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert room.status == "dimmed"
    lights.clear()
    await presence(hass, True)
    await settle(hass)
    (restore,) = lights.calls
    assert dict(restore.data) == {
        "entity_id": [CEILING],
        "brightness": 255,
        "transition": 2,
    }
    assert room.status == "on"
    assert _last(room) == ("restored", "presence_back")
    await advance(hass, freezer, 60, step=5)
    await settle(hass)
    # No flicker: nothing was ever turned off.
    assert lights.of("turn_off") == []
    assert len(lights.calls) == 1


async def test_presence_back_while_waiting_changes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 10)
    await presence(hass, True)
    await advance(hass, freezer, 60, step=5)
    await settle(hass)
    assert lights.calls == []
    assert room.status == "on"
    assert _last(room) == ("turned_on", "presence_dark")


async def test_change_by_someone_else_restarts_the_waits(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 10)
    set_light(hass, CEILING, "on", brightness=100)
    await hass.async_block_till_done()
    assert room.status == "waiting"  # the empty wait starts again
    await advance(hass, freezer, 29)
    await settle(hass)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert room.status == "dimmed"


async def test_change_by_someone_else_while_dimmed_touches_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _lights_on(hass, freezer)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    lights.clear()
    set_light(hass, STRIP, "off")
    await advance(hass, freezer, 29)
    await presence(hass, True)
    await settle(hass)
    # The dimmed light is left as it is; the waits had started again.
    assert lights.calls == []
    assert hass.states.get(CEILING).attributes["brightness"] == 76


async def test_late_state_report_still_ours(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A light that reports its new state without the command's context."""
    entry, _lights = await _lights_on(hass, freezer)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    set_light(hass, CEILING, "on", brightness=77)  # late report, other context
    await advance(hass, freezer, 10)
    await settle(hass)
    assert kitchen(entry).status == "off"


async def test_disabling_cancels_without_touching(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    lights.clear()
    room.set_enabled(False)
    assert room.status == "disabled"
    await advance(hass, freezer, 60, step=5)
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    assert _last(room) == ("skipped_on", "disabled")
    assert hass.states.get(CEILING).attributes["brightness"] == 76


# ------------------------------------------------------------ bright light


async def _known(hass, freezer):
    entry, lights = await _lights_on(hass, freezer)
    _learn(entry, CEILING, 100)
    _learn(entry, STRIP, 50)
    await lux(hass, 160)  # 10 lx of daylight + the lamps
    await advance(hass, freezer, 75, step=5)
    room = kitchen(entry)
    assert (room.ambient, room.held, room.dark) == (10, False, True)
    return entry, lights


async def test_turns_off_when_it_becomes_bright(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _known(hass, freezer)
    room = kitchen(entry)
    await lux(hass, 400)
    assert (room.ambient, room.dark) == (250, False)
    assert room.deadline is not None
    await advance(hass, freezer, 599, step=30)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    # Also with someone in the room.
    assert len(lights.of("turn_off")) == 2
    assert _last(room) == ("turned_off", "bright")


async def test_bright_timer_cancelled_when_dark_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _known(hass, freezer)
    await lux(hass, 400)
    await advance(hass, freezer, 300, step=30)
    await lux(hass, 170)  # 20 lx of daylight: dark again
    assert kitchen(entry).dark is True
    await advance(hass, freezer, 900, step=30)
    assert lights.calls == []


async def test_bright_off_disabled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer, off_when_bright=False)
    _learn(entry, CEILING, 100)
    _learn(entry, STRIP, 50)
    await advance(hass, freezer, 75, step=5)
    await lux(hass, 400)
    await advance(hass, freezer, 900, step=30)
    assert lights.calls == []


async def test_light_turned_on_when_already_bright_stays_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lux="500")
    _learn(entry, CEILING, 100)
    await presence(hass, True)
    set_light(hass, CEILING, "on")
    await lux(hass, 600)
    await advance(hass, freezer, 1800, step=60)
    assert lights.calls == []
    assert hass.states.get(CEILING).state == "on"


# ------------------------------------------------------------- ambient light


async def test_ambient_held_after_a_light_change(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, empty_wait=3600, lux="30")
    _learn(entry, CEILING, 100)
    room = kitchen(entry)
    set_light(hass, CEILING, "on")
    await lux(hass, 130)
    assert (room.ambient, room.held) == (30, True)
    await advance(hass, freezer, 74)
    assert room.held is True
    await advance(hass, freezer, 1)
    assert (room.ambient, room.held) == (30, False)
    # Dimmed to about half: the contribution scales with the brightness.
    set_light(hass, CEILING, "on", brightness=128)
    await lux(hass, 80)
    assert room.held is True
    await advance(hass, freezer, 75)
    assert (room.ambient, room.held) == (30, False)
    state = hass.states.get("sensor.kitchen_bright_rooms_kitchen_ambient_light")
    assert state.state == "30"
    assert state.attributes["raw"] == 80
    assert state.attributes["held"] is False


async def test_ambient_held_while_a_light_is_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, lux="30")
    room = kitchen(entry)
    hass.states.async_set(STRIP, "unavailable")
    await lux(hass, 300)
    await advance(hass, freezer, 120, step=10)
    assert (room.ambient, room.held) == (30, True)
    set_light(hass, STRIP, "off")
    await hass.async_block_till_done()
    # Back from unavailable tells only its state: no settling time.
    assert (room.ambient, room.held) == (300, False)


async def test_ambient_held_while_contribution_unknown(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    # Too bright to learn: the contribution stays unknown.
    entry, _ = await make(
        hass, freezer, empty_wait=3600, lux="30", options={"learn_ambient_max": 10}
    )
    room = kitchen(entry)
    set_light(hass, STRIP, "on")
    await lux(hass, 90)
    await advance(hass, freezer, 120, step=10)
    assert (room.ambient, room.held) == (30, True)
    _learn(entry, STRIP, 50)
    assert (room.ambient, room.held) == (40, False)


async def test_ambient_without_reading(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    room = kitchen(entry)
    hass.states.async_set(LUX, "unavailable")
    await hass.async_block_till_done()
    assert (room.ambient, room.dark) == (None, None)


# ----------------------------------------------------------------- learning


async def _measure(
    hass, freezer, light=CEILING, before=10, after=110, turn_on=True, brightness=None
):
    await lux(hass, before)
    set_light(hass, light, "on" if turn_on else "off", brightness=brightness)
    await advance(hass, freezer, 30, step=5)
    await lux(hass, after)
    await advance(hass, freezer, 45, step=5)


async def test_learns_when_turned_on_and_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, empty_wait=3600)
    room = kitchen(entry)
    await _measure(hass, freezer)
    c = room.contribution(CEILING)
    assert (c.value, c.samples) == (100, 1)
    assert c.updated is not None
    await advance(hass, freezer, 30, step=10)  # on for 90 s in all
    await _measure(hass, freezer, before=110, after=30, turn_on=False)
    c = room.contribution(CEILING)
    # 80 lx this time, weight 0.2.
    assert (c.value, c.samples) == (96, 2)
    state = hass.states.get("sensor.kitchen_bright_rooms_kitchen_contribution_ceiling")
    assert state.state == "96"
    assert state.attributes["samples"] == 2


async def test_learning_normalized_by_brightness(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, empty_wait=3600)
    await _measure(hass, freezer, before=10, after=60, brightness=128)
    assert kitchen(entry).contribution(CEILING).value == 100


async def test_learning_on_off_light(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, empty_wait=3600)
    await _measure(hass, freezer, light=STRIP, before=10, after=40)
    assert kitchen(entry).contribution(STRIP).value == 30


async def test_learns_from_its_own_commands(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, lights=[CEILING])
    await presence(hass, True)
    await settle(hass)
    await lux(hass, 90)
    await advance(hass, freezer, 75, step=5)
    assert kitchen(entry).contribution(CEILING).value == 80


async def test_group_with_one_unknown_light_learns_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Bright Rooms switches both lights together: the known one explains part."""
    entry, _ = await make(hass, freezer)
    _learn(entry, STRIP, 30)
    await presence(hass, True)
    await settle(hass)
    await lux(hass, 140)
    await advance(hass, freezer, 75, step=5)
    room = kitchen(entry)
    assert room.contribution(CEILING).value == 100
    assert (room.contribution(STRIP).value, room.contribution(STRIP).samples) == (30, 0)


async def test_group_with_two_unknown_lights_not_learned(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    await presence(hass, True)
    await settle(hass)
    await lux(hass, 140)
    await advance(hass, freezer, 75, step=5)
    room = kitchen(entry)
    assert room.contribution(CEILING).samples == room.contribution(STRIP).samples == 0


async def test_group_all_known_scaled_together(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, empty_wait=3600)
    _learn(entry, CEILING, 100)
    _learn(entry, STRIP, 50)
    await lux(hass, 10)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 2)  # within the 2 s: one group
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 30, step=5)
    await lux(hass, 310)  # twice the expected 150 lx
    await advance(hass, freezer, 75, step=5)
    room = kitchen(entry)
    assert room.contribution(CEILING).value == 120
    assert room.contribution(STRIP).value == 60
    assert room.contribution(STRIP).samples == 1


async def test_group_by_context(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The same context joins the group also after 2 s (a slow light)."""
    entry, _ = await make(hass, freezer, empty_wait=3600)
    _learn(entry, STRIP, 30)
    context = Context()
    await lux(hass, 10)
    set_light(hass, CEILING, "on", context=context)
    await advance(hass, freezer, 5)
    set_light(hass, STRIP, "on", context=context)
    await lux(hass, 140)
    await advance(hass, freezer, 75, step=5)
    assert kitchen(entry).contribution(CEILING).value == 100


async def test_group_in_opposite_directions_not_learned(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_light(hass, STRIP, "on")
    entry, _ = await make(hass, freezer)
    _learn(entry, STRIP, 30)
    await lux(hass, 40)
    set_light(hass, CEILING, "on")
    set_light(hass, STRIP, "off")
    await lux(hass, 110)
    await advance(hass, freezer, 100, step=10)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_not_learned_with_daylight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    await _measure(hass, freezer, before=100, after=200)
    assert kitchen(entry).contribution(CEILING).samples == 0
    await advance(hass, freezer, 100, step=10)
    # Turning off: the ambient light that counts is the one after.
    await _measure(hass, freezer, before=200, after=70, turn_on=False)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_not_learned_after_a_short_previous_state(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 20)
    # Cancels the measurement of turning on; on for 20 s only: not measured.
    await _measure(hass, freezer, before=110, after=10, turn_on=False)
    await advance(hass, freezer, 100, step=10)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_not_learned_when_the_light_changes_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    await lux(hass, 10)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 20)
    set_light(hass, CEILING, "on", brightness=200)
    await lux(hass, 110)
    await advance(hass, freezer, 100, step=10)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_not_learned_when_another_room_light_changed_before(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    _learn(entry, STRIP, 30)
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 29)
    await _measure(hass, freezer, before=40, after=140)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_learned_when_other_light_changed_long_before(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, empty_wait=3600)
    _learn(entry, STRIP, 30)
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 31)
    await _measure(hass, freezer, before=40, after=140)
    assert kitchen(entry).contribution(CEILING).value == 100


async def test_not_learned_when_another_room_light_changes_during(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    await lux(hass, 10)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 10)
    set_light(hass, STRIP, "on")
    await lux(hass, 140)
    await advance(hass, freezer, 100, step=10)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_not_learned_when_an_other_light_changes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer, **{CONF_OTHER_LIGHTS: [OTHER]})
    await lux(hass, 10)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 10)
    set_light(hass, OTHER, "on")
    await lux(hass, 110)
    await advance(hass, freezer, 100, step=10)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_unrelated_light_does_not_spoil(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """OTHER is not among the room's other lights here."""
    entry, _ = await make(hass, freezer, empty_wait=3600)
    await lux(hass, 10)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 10)
    set_light(hass, OTHER, "on")
    await lux(hass, 110)
    await advance(hass, freezer, 100, step=10)
    assert kitchen(entry).contribution(CEILING).value == 100


async def test_not_learned_with_a_small_jump(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    await _measure(hass, freezer, before=10, after=14)
    assert kitchen(entry).contribution(CEILING).samples == 0


async def test_not_learned_out_of_range(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    _learn(entry, CEILING, 100)
    await _measure(hass, freezer, before=10, after=410)
    c = kitchen(entry).contribution(CEILING)
    assert (c.value, c.samples) == (100, 0)


async def test_not_learned_without_a_reading(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
    await _measure(hass, freezer, before=10, after="unavailable")
    assert kitchen(entry).contribution(CEILING).samples == 0


# ------------------------------------------------------- unreliable lights


def _detail(room) -> str | None:
    return room.last_action.detail if room.last_action else None


async def test_failed_call_retried(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    room = kitchen(entry)
    lights.failures = 1  # the strip's call raises
    await presence(hass, True)
    await settle(hass)
    assert hass.states.get(STRIP).state == "off"
    assert hass.states.get(CEILING).state == "on"
    assert _last(room) == ("failed", "presence_dark")
    assert _detail(room) == "Device communication error"
    assert room.snapshot()["goal"] == "on"
    lights.clear()
    await advance(hass, freezer, 10)
    await settle(hass)
    # Only the light that did not follow.
    assert [c.data["entity_id"] for c in lights.calls] == [[STRIP]]
    assert hass.states.get(STRIP).state == "on"
    assert _last(room) == ("turned_on", "presence_dark")
    assert _detail(room) is None
    assert room.snapshot()["goal"] is None
    await advance(hass, freezer, 60, step=10)
    assert len(lights.calls) == 1


async def test_light_that_does_not_follow(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog
) -> None:
    entry, lights = await make(hass, freezer, lights=[STRIP])
    room = kitchen(entry)
    lights.deaf.add(STRIP)
    await presence(hass, True)
    await settle(hass)
    await advance(hass, freezer, 60, step=5)
    await settle(hass)
    assert len(lights.calls) == 3  # three attempts, 10 s apart
    assert _last(room) == ("failed", "presence_dark")
    assert _detail(room) == "no response"
    assert caplog.text.count("did not turn on after 3 attempts") == 1
    assert room.snapshot()["goal"] == "on"  # kept for when it comes back


async def test_failed_three_times_then_light_back(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lights=[STRIP])
    room = kitchen(entry)
    lights.failures = 3
    await presence(hass, True)
    await advance(hass, freezer, 60, step=5)
    await settle(hass)
    assert len(lights.calls) == 3
    assert _last(room) == ("failed", "presence_dark")
    hass.states.async_set(STRIP, "unavailable")
    await hass.async_block_till_done()
    set_light(hass, STRIP, "off")
    await settle(hass)
    assert len(lights.calls) == 4
    assert hass.states.get(STRIP).state == "on"
    assert _last(room) == ("turned_on", "light_back")
    assert room.snapshot()["goal"] is None


async def test_arrival_while_unavailable_then_light_back(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lights=[STRIP])
    room = kitchen(entry)
    hass.states.async_set(STRIP, "unavailable")
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    assert room.snapshot()["goal"] == "on"
    await advance(hass, freezer, 4)
    set_light(hass, STRIP, "off")
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_on"]
    assert _last(room) == ("turned_on", "light_back")


async def test_light_back_respects_min_off_seconds(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await make(
        hass, freezer, lights=[STRIP], **{CONF_MIN_OFF_SECONDS: 20}
    )
    hass.states.async_set(STRIP, "unavailable")
    await presence(hass, True)
    set_light(hass, STRIP, "off")
    await advance(hass, freezer, 19)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.calls) == 1


async def test_light_back_with_brightness_from_the_curve(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await make(
        hass, freezer, lux="30", lights=[CEILING], **{CONF_BRIGHTNESS_MIN: 20}
    )
    hass.states.async_set(CEILING, "unavailable")
    await presence(hass, True)
    set_light(hass, CEILING, "off")
    await settle(hass)
    (call,) = lights.calls
    assert call.data["brightness_pct"] == 28


async def test_light_back_catches_up_on_an_arrival(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """No goal any more (it was reached), but the light restarted off."""
    entry, lights = await _lights_on(hass, freezer, lights=[CEILING])
    hass.states.async_set(CEILING, "unavailable")
    await hass.async_block_till_done()
    set_light(hass, CEILING, "off")
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_on"]
    assert _last(kitchen(entry)) == ("turned_on", "light_back")


async def test_light_back_after_manual_off_stays_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _lights_on(hass, freezer, lights=[CEILING])
    set_light(hass, CEILING, "off")  # by hand, with someone in the room
    await advance(hass, freezer, 30, step=10)
    for _ in range(2):
        hass.states.async_set(CEILING, "unavailable")
        await hass.async_block_till_done()
        set_light(hass, CEILING, "off")
        await advance(hass, freezer, 30, step=10)
    assert lights.calls == []


async def test_turn_off_raised_but_executed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer, lights=[CEILING], dim_percent=100)
    room = kitchen(entry)
    lights.failures = 1
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]
    assert _last(room) == ("failed", "empty")
    assert hass.states.get(CEILING).state == "on"
    await advance(hass, freezer, 5)
    set_light(hass, CEILING, "off")  # reported late, without our context
    await settle(hass)
    assert _last(room) == ("turned_off", "empty")
    assert room.snapshot()["goal"] is None
    # Not taken for someone else's change: the next arrival turns on again.
    await advance(hass, freezer, 60, step=10)
    assert len(lights.calls) == 1
    await presence(hass, True)
    await settle(hass)
    assert lights.calls[-1].service == "turn_on"


async def test_goal_cleared_when_the_room_empties(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lights=[STRIP])
    room = kitchen(entry)
    hass.states.async_set(STRIP, "unavailable")
    await presence(hass, True)
    assert room.snapshot()["goal"] == "on"
    await presence(hass, False)
    assert room.snapshot()["goal"] is None
    set_light(hass, STRIP, "off")
    await advance(hass, freezer, 60, step=10)
    assert lights.calls == []


async def test_goal_cleared_when_disabled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lights=[STRIP])
    room = kitchen(entry)
    hass.states.async_set(STRIP, "unavailable")
    await presence(hass, True)
    assert room.snapshot()["goal"] == "on"
    room.set_enabled(False)
    assert room.snapshot()["goal"] is None
    set_light(hass, STRIP, "off")
    await advance(hass, freezer, 30, step=10)
    assert lights.calls == []


async def test_goal_cleared_when_bright(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    room = kitchen(entry)
    _learn(entry, CEILING, 100)
    _learn(entry, STRIP, 50)
    lights.deaf.add(STRIP)
    await presence(hass, True)
    await settle(hass)
    await lux(hass, 110)
    await advance(hass, freezer, 75, step=5)
    assert (room.ambient, room.snapshot()["goal"]) == (10, "on")
    await lux(hass, 500)
    assert room.dark is False
    assert room.snapshot()["goal"] is None


async def test_goal_cleared_by_someone_else(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    lights.deaf.add(STRIP)
    await presence(hass, True)
    await settle(hass)
    set_light(hass, CEILING, "off")  # by hand: their choice wins
    await advance(hass, freezer, 60, step=10)
    assert len(lights.calls) == 2  # no retries
    assert kitchen(entry).snapshot()["goal"] is None


async def test_bright_turn_off_goal_cleared_when_dark_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _known(hass, freezer)
    lights.deaf.update({CEILING, STRIP})
    await lux(hass, 400)
    await advance(hass, freezer, 600, step=30)
    await settle(hass)
    room = kitchen(entry)
    assert room.snapshot()["goal"] == "off"
    await lux(hass, 160)  # ambient 10: dark again
    assert room.snapshot()["goal"] is None


# --------------------------------------------------------------- time bands

# make() sets up the room at 20:10, a Monday.
BAND_EVENING = {
    "id": "eve",
    "name": "Evening",
    "start": "18:00",
    "end": "23:00",
    "days": [],
    "empty_wait": 120,
    "zone_wait": None,
}


async def test_band_overrides_the_empty_wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(
        hass, freezer, dim_percent=100, schedule=[BAND_EVENING]
    )
    room = kitchen(entry)
    assert room.active_band().id == "eve"
    assert room.effective() == {
        "on_delay": 0,
        "empty_wait": 120,
        "zone_wait": 150,
        "zone_sensors": [ZONE],
    }
    await presence(hass, False)
    await advance(hass, freezer, 119, step=7)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_off")) == 2


async def test_band_partial_override_and_zone_wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {**BAND_EVENING, "empty_wait": None, "zone_wait": 20}
    entry, lights = await _lights_on(hass, freezer, dim_percent=100, schedule=[band])
    eff = kitchen(entry).effective()
    assert (eff["empty_wait"], eff["zone_wait"]) == (30, 20)
    hass.states.async_set(ZONE, "on")
    await presence(hass, False)
    await advance(hass, freezer, 20)  # zone wait over, then the room's 30 s
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_off")) == 2


async def test_band_read_when_the_wait_starts(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The band ends during the wait: the wait keeps its length."""
    band = {**BAND_EVENING, "start": "19:00", "end": "20:11"}
    entry, lights = await _lights_on(hass, freezer, dim_percent=100, schedule=[band])
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 90, step=10)
    assert room.active_band() is None
    assert lights.calls == []
    await advance(hass, freezer, 30, step=10)
    await settle(hass)
    assert len(lights.of("turn_off")) == 2


async def test_band_shown_on_the_status_sensor(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {**BAND_EVENING, "name": None, "start": "20:00", "end": "20:15"}
    entry, _ = await make(hass, freezer, schedule=[band])
    status = "sensor.kitchen_bright_rooms_kitchen_status"
    assert hass.states.get(status).attributes["active_band"] == "20:00–20:15"
    snap = kitchen(entry).snapshot()
    assert snap["active_band"] == "eve"
    assert snap["effective"] == {
        "on_delay": 0,
        "empty_wait": 120,
        "zone_wait": 150,
        "zone_sensors": [ZONE],
    }
    # The band ends at 20:15: the sensor updates by itself.
    await advance(hass, freezer, 300, step=60)
    assert hass.states.get(status).attributes["active_band"] is None
    assert kitchen(entry).snapshot()["effective"]["empty_wait"] == 30


# ----------------------------------------------------------------- re-entry


async def test_back_right_after_the_lights_went_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 40)  # dimmed at 30 s, off at 40 s
    await settle(hass)
    assert room.status == "off"
    lights.clear()
    await advance(hass, freezer, 9)
    await presence(hass, True)
    await settle(hass)
    calls = {tuple(c.data["entity_id"]): dict(c.data) for c in lights.of("turn_on")}
    # Back as before the dimming.
    assert calls == {
        (CEILING,): {"entity_id": [CEILING], "brightness": 255},
        (STRIP,): {"entity_id": [STRIP]},
    }
    assert _last(room) == ("turned_on", "presence_back")


async def test_back_after_the_window_is_a_normal_arrival(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    await presence(hass, False)
    await advance(hass, freezer, 40)
    await settle(hass)
    lights.clear()
    await advance(hass, freezer, 11)
    await presence(hass, True)
    await settle(hass)
    assert _last(kitchen(entry)) == ("turned_on", "presence_dark")
    (dimmed,) = [c for c in lights.of("turn_on") if c.data["entity_id"] == [CEILING]]
    assert dimmed.data["brightness_pct"] == 100


async def test_back_while_the_turn_off_is_in_flight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The bug: arrival seen while the light was still on, then it went off."""
    entry, lights = await _lights_on(hass, freezer, lights=[CEILING], dim_percent=100)
    room = kitchen(entry)
    lights.deaf.add(CEILING)  # the command is on its way
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]
    await presence(hass, True)  # back in the same second: the light is still on
    await settle(hass)
    assert len(lights.calls) == 1
    lights.deaf.clear()
    set_light(hass, CEILING, "off")  # the light reports off (no context)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off", "turn_on"]
    assert hass.states.get(CEILING).state == "on"
    assert _last(room) == ("turned_on", "presence_back")


async def test_gone_again_while_in_flight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _lights_on(hass, freezer, lights=[CEILING], dim_percent=100)
    lights.deaf.add(CEILING)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    await presence(hass, True)
    await presence(hass, False)
    set_light(hass, CEILING, "off")
    await advance(hass, freezer, 30, step=10)
    assert [c.service for c in lights.calls] == ["turn_off"]


async def test_back_respects_min_off_seconds(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _lights_on(
        hass, freezer, lights=[CEILING], dim_percent=100, **{CONF_MIN_OFF_SECONDS: 8}
    )
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    lights.clear()
    await advance(hass, freezer, 2)
    await presence(hass, True)
    await advance(hass, freezer, 5)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_on"]


async def test_back_after_someone_else_changed_a_light(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer, dim_percent=100)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    lights.clear()
    set_light(hass, STRIP, "on")  # by hand
    await presence(hass, True)
    await settle(hass)
    # Not turned back on (the strip was turned on by hand, which started the
    # empty waits); the arrival cancels them.
    assert lights.calls == []
    assert kitchen(entry).status == "on"


async def test_no_reentry_after_the_bright_turn_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _known(hass, freezer)
    await lux(hass, 400)
    await advance(hass, freezer, 600, step=30)
    await settle(hass)
    assert _last(kitchen(entry)) == ("turned_off", "bright")
    lights.clear()
    await presence(hass, False)
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    assert _last(kitchen(entry)) == ("skipped_on", "not_dark")


# -------------------------------------------------- empty room, lights on


async def test_night_failed_turn_off_then_flapping_light(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """04:36 on; 04:38:55 turn-off raised; unavailable; a brief arrival while
    unavailable; 04:54 back on with the room empty: off after the waits."""
    entry, lights = await _lights_on(hass, freezer, lights=[CEILING], dim_percent=100)
    room = kitchen(entry)
    lights.failures = 1
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert _last(room) == ("failed", "empty")
    await advance(hass, freezer, 2)
    hass.states.async_set(CEILING, "unavailable")
    await advance(hass, freezer, 49)
    await presence(hass, True)  # clears the off goal
    await advance(hass, freezer, 21)
    await presence(hass, False)  # the light is unavailable: nothing to do yet
    await advance(hass, freezer, 14 * 60, step=60)
    lights.clear()
    set_light(hass, CEILING, "on")  # back, with the relay on
    await settle(hass)
    assert room.status == "waiting"
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]
    assert hass.states.get(CEILING).state == "off"
    assert _last(room) == ("turned_off", "empty")


async def test_night_light_back_on_in_an_empty_room(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """00:18 unavailable with the room empty, 01:21 back on: off after the waits."""
    entry, lights = await make(hass, freezer, lights=[CEILING], dim_percent=100)
    hass.states.async_set(CEILING, "unavailable")
    await advance(hass, freezer, 3600, step=600)
    set_light(hass, CEILING, "on")
    await advance(hass, freezer, 30)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]
    assert kitchen(entry).status == "off"


async def test_wall_switch_in_an_empty_room(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    set_light(hass, STRIP, "on")  # wall switch, nobody detected
    await hass.async_block_till_done()
    assert kitchen(entry).status == "waiting"
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]
    assert _last(kitchen(entry)) == ("turned_off", "empty")


async def test_light_on_in_an_empty_room_with_the_zone_occupied(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    hass.states.async_set(ZONE, "on")
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 150 + 29, step=1)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]
    assert _last(kitchen(entry)) == ("turned_off", "zone_timeout")


async def test_light_on_in_an_empty_room_uses_the_band(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await make(hass, freezer, schedule=[BAND_EVENING])
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 119, step=7)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_off"]


async def test_light_on_in_an_empty_disabled_room(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    kitchen(entry).set_enabled(False)
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 600, step=30)
    assert lights.calls == []


async def test_someone_back_while_the_waits_run(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer)
    set_light(hass, STRIP, "on")
    await advance(hass, freezer, 20)
    await presence(hass, True)
    await advance(hass, freezer, 120, step=10)
    assert lights.calls == []
    assert kitchen(entry).status == "on"


# -------------------------------------------------------- bands on light

LIVING_LUX = "sensor.living_illuminance"
HALL = "binary_sensor.hall_presence"


def _room_named(entry, title: str):
    return next(r for r in entry.runtime_data.rooms.values() if r.title == title)


async def _with_living(hass, freezer, band, **room):
    """The kitchen, plus a living room; `band(living_id)` is the kitchen's band."""
    entry, lights = await make(hass, freezer, **room)
    hass.states.async_set(LIVING_LUX, "10", {"device_class": "illuminance"})
    hass.states.async_set("binary_sensor.living_presence", "off")
    area = ar.async_get(hass).async_create("Living")
    living = ConfigSubentry(
        data=MappingProxyType(
            {
                **ROOM_DEFAULTS,
                "name": "Living",
                "area": area.id,
                "presence_sensors": ["binary_sensor.living_presence"],
                "lights": [OTHER],
                "illuminance_sensor": LIVING_LUX,
                "schedule": [],
            }
        ),
        subentry_type="room",
        title="Living",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, living)
    await hass.async_block_till_done()
    sub = next(s for s in entry.subentries.values() if s.title == "Kitchen")
    hass.config_entries.async_update_subentry(
        entry, sub, data={**sub.data, "schedule": [band(living.subentry_id)]}
    )
    await hass.async_block_till_done()
    return entry, lights, living.subentry_id


async def test_band_on_another_rooms_light(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _, _living_id = await _with_living(
        hass,
        freezer,
        lambda living: {
            "id": "b",
            "name": None,
            "light": "dark",
            "light_room": living,
            "empty_wait": 300,
        },
    )
    room = _room_named(entry, "Kitchen")
    status = "sensor.kitchen_bright_rooms_kitchen_status"
    assert room.active_band().id == "b"
    assert room.effective()["empty_wait"] == 300
    assert hass.states.get(status).attributes["active_band"] == "dark"
    hass.states.async_set(LIVING_LUX, "500", {"device_class": "illuminance"})
    await hass.async_block_till_done()
    # The living room is bright now: the kitchen's band ends at once.
    assert _room_named(entry, "Living").dark is False
    assert room.active_band() is None
    assert hass.states.get(status).attributes["active_band"] is None
    assert room.snapshot()["effective"]["empty_wait"] == 30


async def test_band_on_another_rooms_light_updates_subscriptions(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    _entry, _, _ = await _with_living(
        hass,
        freezer,
        lambda living: {
            "id": "b",
            "light": "dark",
            "light_room": living,
            "on_delay": 60,
        },
    )
    await client.send_json_auto_id({"type": "bright_rooms/subscribe"})
    assert (await client.receive_json())["success"]
    event = (await client.receive_json())["event"]
    kitchen_snap = next(r for r in event["rooms"] if r["name"] == "Kitchen")
    assert kitchen_snap["active_band"] == "b"
    await advance(hass, freezer, 1)
    hass.states.async_set(LIVING_LUX, "500", {"device_class": "illuminance"})
    await hass.async_block_till_done()
    await advance(hass, freezer, 1)
    event = (await client.receive_json())["event"]
    kitchen_snap = next(r for r in event["rooms"] if r["name"] == "Kitchen")
    assert kitchen_snap["active_band"] is None
    assert kitchen_snap["effective"]["on_delay"] == 0


async def test_on_delay_by_day_and_evening(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Bright: 120 s of presence before turning on; dark: the room's 0 s."""
    band = {"id": "day", "light": "bright", "on_delay": 120}
    entry, lights = await make(
        hass, freezer, lux="500", schedule=[band], **{CONF_ONLY_WHEN_DARK: False}
    )
    assert kitchen(entry).effective()["on_delay"] == 120
    await presence(hass, True)
    await advance(hass, freezer, 119, step=7)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_on_delay_band_inactive_in_the_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {"id": "day", "light": "bright", "on_delay": 120}
    entry, lights = await make(hass, freezer, schedule=[band])
    assert kitchen(entry).active_band() is None
    await presence(hass, True)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_light_band_with_unknown_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {"id": "dark", "light": "dark", "on_delay": 120}
    entry, lights = await make(hass, freezer, lux=None, schedule=[band])
    assert kitchen(entry).dark is None
    assert kitchen(entry).active_band() is None
    await presence(hass, True)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_light_and_time_band_in_the_engine(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    band = {
        "id": "x",
        "start": "18:00",
        "end": "23:00",
        "light": "dark",
        "empty_wait": 120,
    }
    entry, _ = await make(hass, freezer, schedule=[band])
    room = kitchen(entry)
    assert room.active_band().id == "x"  # 20:10, dark
    status = "sensor.kitchen_bright_rooms_kitchen_status"
    assert hass.states.get(status).attributes["active_band"] == "18:00–23:00 · dark"
    await lux(hass, 500)
    assert room.active_band() is None
    assert hass.states.get(status).attributes["active_band"] is None


async def test_band_without_zone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """`zone_sensors: []`: no zone wait in this band."""
    band = {**BAND_EVENING, "empty_wait": None, "zone_sensors": []}
    entry, lights = await _lights_on(hass, freezer, dim_percent=100, schedule=[band])
    assert kitchen(entry).effective()["zone_sensors"] == []
    hass.states.async_set(ZONE, "on")
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    assert len(lights.of("turn_off")) == 2
    assert _last(kitchen(entry)) == ("turned_off", "empty")


async def test_band_with_other_zone_sensors(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(HALL, "off")
    band = {**BAND_EVENING, "empty_wait": None, "zone_sensors": [HALL]}
    entry, lights = await _lights_on(hass, freezer, dim_percent=100, schedule=[band])
    room = kitchen(entry)
    hass.states.async_set(ZONE, "on")  # not watched in this band
    hass.states.async_set(HALL, "on")
    await presence(hass, False)
    assert room.status == "waiting" and room.zone_occupied
    await advance(hass, freezer, 60, step=10)
    hass.states.async_set(HALL, "off")  # the hall empties: the empty wait starts
    await hass.async_block_till_done()
    await advance(hass, freezer, 29)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert len(lights.of("turn_off")) == 2
    assert _last(room) == ("turned_off", "empty")


# ------------------------------------------------------ undecided darkness


async def test_restart_in_daylight_light_reported_off_late(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The light is unavailable at start and reported off by its integration;
    someone comes in at once: full daylight, no turn-on."""
    hass.states.async_set(CEILING, "unavailable")
    entry, lights = await make(hass, freezer, lux="750", lights=[CEILING])
    room = kitchen(entry)
    assert room.dark is None and room.dark_undecided
    await advance(hass, freezer, 30)
    set_light(hass, CEILING, "off")
    await hass.async_block_till_done()
    assert (room.ambient, room.dark) == (750, False)
    await advance(hass, freezer, 40)
    await presence(hass, True)
    await advance(hass, freezer, 120, step=10)
    assert lights.calls == []
    assert _last(room) == ("skipped_on", "not_dark")


async def test_restart_with_a_light_on_and_known_contribution(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage
) -> None:
    entry_id, room_id = (
        "entry0000000000000000000000000",
        "room00000000000000000000000000",
    )
    hass_storage[f"bright_rooms.{entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"bright_rooms.{entry_id}",
        "data": {
            "rooms": {
                room_id: {
                    "enabled": True,
                    "contributions": {
                        CEILING: {"value": 100, "samples": 3, "updated": None}
                    },
                }
            }
        },
    }
    set_light(hass, CEILING, "on")
    entry, _ = await make(
        hass, freezer, lux="600", lights=[CEILING], entry_id=entry_id, room_id=room_id
    )
    room = kitchen(entry)
    assert (room.ambient, room.held, room.dark) == (500, False, False)


async def test_arrival_waits_for_an_undecided_dark_state(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """No earlier ambient value and a light change during the run: the turn-on
    waits for the settling time, then decides by the new value."""
    entry, lights = await make(
        hass, freezer, lux=None, lights=[CEILING], empty_wait=3600
    )
    room = kitchen(entry)
    set_light(hass, CEILING, "on")
    set_light(hass, CEILING, "off")  # held for 75 s from now
    await lux(hass, 500)
    assert room.dark_undecided
    await advance(hass, freezer, 5)
    await presence(hass, True)
    await advance(hass, freezer, 60, step=5)
    assert lights.calls == []
    assert room.last_action is None  # still waiting
    await advance(hass, freezer, 15, step=5)  # the hold ends: 500 lx
    await settle(hass)
    assert room.dark is False
    assert lights.calls == []
    assert _last(room) == ("skipped_on", "not_dark")


async def test_arrival_waits_then_turns_on_in_the_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(
        hass, freezer, lux=None, lights=[CEILING], empty_wait=3600
    )
    set_light(hass, CEILING, "on")
    set_light(hass, CEILING, "off")
    await lux(hass, 10)
    await presence(hass, True)
    await settle(hass)
    assert lights.calls == []
    await advance(hass, freezer, 75, step=5)
    await settle(hass)
    assert [c.service for c in lights.calls] == ["turn_on"]
    assert _last(kitchen(entry)) == ("turned_on", "presence_dark")


async def test_undecided_too_long_counts_as_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A light stays unavailable (ambient never known): after settle + 15 s."""
    hass.states.async_set(STRIP, "unavailable")
    entry, lights = await make(hass, freezer, lux="500")
    assert kitchen(entry).dark_undecided
    await presence(hass, True)
    await advance(hass, freezer, 89)
    assert lights.calls == []
    await advance(hass, freezer, 1)
    await settle(hass)
    assert [c.data["entity_id"] for c in lights.calls] == [[CEILING]]
    assert _last(kitchen(entry)) == ("turned_on", "presence_dark")


async def test_unavailable_sensor_counts_as_dark_at_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, lux="500")
    hass.states.async_set(LUX, "unavailable")
    await hass.async_block_till_done()
    room = kitchen(entry)
    assert room.dark is None and not room.dark_undecided
    await presence(hass, True)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2


async def test_no_sensor_always_dark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await make(hass, freezer, illuminance_sensor=None)
    assert not kitchen(entry).dark_undecided
    await presence(hass, True)
    await settle(hass)
    assert len(lights.of("turn_on")) == 2
