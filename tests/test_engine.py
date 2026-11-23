"""Engine tests: turning on, turning off, daylight, holds and learning."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant

from custom_components.bright_rooms.const import (
    CONF_BRIGHTNESS_MIN,
    CONF_MIN_OFF_SECONDS,
    CONF_ON_DELAY,
    CONF_ONLY_WHEN_DARK,
    CONF_OTHER_LIGHTS,
)

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
    entry, lights = await make(hass, freezer)
    set_light(hass, STRIP, "on")
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


async def test_startup_turn_off_skipped_after_a_change_by_hand(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_light(hass, CEILING, "on")
    entry, lights = await make(hass, freezer)
    await advance(hass, freezer, 10)
    set_light(hass, CEILING, "on", brightness=100)
    await advance(hass, freezer, 120, step=10)
    assert lights.calls == []
    assert kitchen(entry).status == "on"


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
    _entry, lights = await _lights_on(hass, freezer)
    hass.states.async_set(PRESENCE, "unavailable")
    await hass.async_block_till_done()
    await presence(hass, False)
    await advance(hass, freezer, 600, step=30)
    assert lights.calls == []


# ----------------------------------------------------------------- turn off


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


async def test_change_by_someone_else_cancels_turning_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, lights = await _lights_on(hass, freezer)
    room = kitchen(entry)
    await presence(hass, False)
    await advance(hass, freezer, 10)
    set_light(hass, CEILING, "on", brightness=100)
    await hass.async_block_till_done()
    assert room.status == "on"
    await advance(hass, freezer, 120, step=5)
    await settle(hass)
    assert lights.calls == []


async def test_change_by_someone_else_while_dimmed_touches_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    _entry, lights = await _lights_on(hass, freezer)
    await presence(hass, False)
    await advance(hass, freezer, 30)
    await settle(hass)
    lights.clear()
    set_light(hass, STRIP, "off")
    await advance(hass, freezer, 30)
    await presence(hass, True)
    await settle(hass)
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
    entry, _ = await make(hass, freezer, lux="30")
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
    assert room.held is True  # back from unavailable: settling time
    await advance(hass, freezer, 75, step=5)
    assert (room.ambient, room.held) == (300, False)


async def test_ambient_held_while_contribution_unknown(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    # Too bright to learn: the contribution stays unknown.
    entry, _ = await make(hass, freezer, lux="30", options={"learn_ambient_max": 10})
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
    entry, _ = await make(hass, freezer)
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
    entry, _ = await make(hass, freezer)
    await _measure(hass, freezer, before=10, after=60, brightness=128)
    assert kitchen(entry).contribution(CEILING).value == 100


async def test_learning_on_off_light(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = await make(hass, freezer)
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
    entry, _ = await make(hass, freezer)
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
    entry, _ = await make(hass, freezer)
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
    entry, _ = await make(hass, freezer)
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
    entry, _ = await make(hass, freezer)
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
