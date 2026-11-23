"""Runtime engine: one RoomEngine per room, owned by the entry's engine."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    brightness_supported,
)
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .ambient import (
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
from .const import (
    CONF_AREA,
    CONF_BRIGHT_ABOVE,
    CONF_BRIGHT_MINUTES,
    CONF_BRIGHTNESS_DARK_LUX,
    CONF_BRIGHTNESS_FULL_LUX,
    CONF_BRIGHTNESS_MIN,
    CONF_DARK_BELOW,
    CONF_DIM_PERCENT,
    CONF_DIM_WAIT,
    CONF_EMPTY_WAIT,
    CONF_ILLUMINANCE_SENSOR,
    CONF_LEARN_AMBIENT_MAX,
    CONF_LEARN_MIN_PREVIOUS,
    CONF_LEARN_WEIGHT,
    CONF_LIGHTS,
    CONF_MIN_OFF_SECONDS,
    CONF_NAME,
    CONF_OFF_WHEN_BRIGHT,
    CONF_ON_DELAY,
    CONF_ON_WHEN_DARK,
    CONF_ONLY_WHEN_DARK,
    CONF_OTHER_LIGHTS,
    CONF_PRESENCE_SENSORS,
    CONF_SCHEDULE,
    CONF_SETTLE_SECONDS,
    CONF_TRANSITION,
    CONF_ZONE_SENSORS,
    CONF_ZONE_WAIT,
    DIM_TRANSITION,
    DOMAIN,
    GOAL_ATTEMPTS,
    GOAL_RETRY_SECONDS,
    LEARN_GROUP_SECONDS,
    LEARN_QUIET_BEFORE,
    REENTRY_SECONDS,
    ROOM_DEFAULTS,
    STARTUP_GRACE,
    SUBENTRY_ROOM,
    Action,
    Reason,
    Status,
)
from .schedule import Band, active_band, next_boundary
from .schema import room_config, room_title, settings
from .store import BrightRoomsStore, Contribution

_LOGGER = logging.getLogger(__name__)

_BAD = (STATE_UNAVAILABLE, STATE_UNKNOWN)
# Domains of the presence sensors' own settings shown in the panel.
SENSOR_SETTING_DOMAINS = ("number", "select", "switch", "button")
# A state that matches what Bright Rooms asked for, reported without its
# context up to this long after the end of the transition, is still ours:
# Home Assistant keeps an entity's context for 5 s, some lights report later.
EXPECT_SECONDS = 5


def update_signal(entry_id: str) -> str:
    """Dispatcher signal sent when anything of an entry changes."""
    return f"{DOMAIN}_{entry_id}_update"


def room_signal(room_id: str) -> str:
    """Dispatcher signal sent when a room changes."""
    return f"{DOMAIN}_{room_id}_room_update"


def _iso(value: datetime | None) -> str | None:
    return dt_util.as_local(value).isoformat() if value else None


def _available(state: State | None) -> bool:
    return state is not None and state.state not in _BAD


@dataclass(frozen=True, slots=True)
class RoomConfig:
    """Settings of a room (subentry data with defaults)."""

    area_id: str
    presence_sensors: tuple[str, ...]
    zone_sensors: tuple[str, ...]
    lights: tuple[str, ...]
    illuminance_sensor: str | None
    other_lights: tuple[str, ...]
    on_delay: float
    only_when_dark: bool
    dark_below: float
    bright_above: float
    off_when_bright: bool
    on_when_dark: bool
    bright_minutes: float
    min_off_seconds: float
    brightness_min: float
    brightness_dark_lux: float
    brightness_full_lux: float
    empty_wait: float
    zone_wait: float
    dim_percent: float
    dim_wait: float
    transition: float
    schedule: tuple[Band, ...] = ()

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> RoomConfig:
        """Read a room's subentry data."""
        d = {**ROOM_DEFAULTS, **data}
        return cls(
            area_id=d[CONF_AREA],
            presence_sensors=tuple(d.get(CONF_PRESENCE_SENSORS) or ()),
            zone_sensors=tuple(d.get(CONF_ZONE_SENSORS) or ()),
            lights=tuple(d.get(CONF_LIGHTS) or ()),
            illuminance_sensor=d.get(CONF_ILLUMINANCE_SENSOR) or None,
            other_lights=tuple(d.get(CONF_OTHER_LIGHTS) or ()),
            on_delay=float(d[CONF_ON_DELAY]),
            only_when_dark=bool(d[CONF_ONLY_WHEN_DARK]),
            dark_below=float(d[CONF_DARK_BELOW]),
            bright_above=float(d[CONF_BRIGHT_ABOVE]),
            off_when_bright=bool(d[CONF_OFF_WHEN_BRIGHT]),
            on_when_dark=bool(d[CONF_ON_WHEN_DARK]),
            bright_minutes=float(d[CONF_BRIGHT_MINUTES]),
            min_off_seconds=float(d[CONF_MIN_OFF_SECONDS]),
            brightness_min=float(d[CONF_BRIGHTNESS_MIN]),
            brightness_dark_lux=float(d[CONF_BRIGHTNESS_DARK_LUX]),
            brightness_full_lux=float(d[CONF_BRIGHTNESS_FULL_LUX]),
            empty_wait=float(d[CONF_EMPTY_WAIT]),
            zone_wait=float(d[CONF_ZONE_WAIT]),
            dim_percent=float(d[CONF_DIM_PERCENT]),
            dim_wait=float(d[CONF_DIM_WAIT]),
            transition=float(d[CONF_TRANSITION]),
            schedule=tuple(_bands(d.get(CONF_SCHEDULE) or [])),
        )


def _bands(raw: list[Any]) -> list[Band]:
    bands = []
    for item in raw:
        try:
            bands.append(Band.from_data(item))
        except KeyError, TypeError, ValueError:
            _LOGGER.warning("Ignoring an invalid time band: %s", item)
    return bands


@dataclass(slots=True)
class Reentry:
    """Lights an empty room's turn-off switched off: back on if someone returns."""

    lights: dict[str, int | None]  # light -> brightness to restore (None: just on)
    until: datetime  # end of the window
    in_flight: bool = True  # the lights have not all reported off yet
    arrived: bool = False  # someone came back while in flight


@dataclass(frozen=True, slots=True)
class LastAction:
    """The last thing a room did, or decided not to do."""

    action: Action
    reason: Reason
    at: datetime
    detail: str | None = None  # why a command failed

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready."""
        return {
            "action": self.action.value,
            "reason": self.reason.value,
            "at": _iso(self.at),
            "detail": self.detail,
        }


@dataclass(slots=True)
class OffSequence:
    """Turning off an empty room: zone wait, empty wait, dimmed warning."""

    phase: str = "empty"  # "zone", "empty" or "dimmed"
    zone_until: datetime | None = None  # end of the longest zone wait
    zone_timed_out: bool = False
    deadline: datetime | None = None
    remembered: dict[str, int] = field(
        default_factory=dict
    )  # brightness before dimming


@dataclass(slots=True)
class Goal:
    """What the room's lights should be after Bright Rooms' last decision."""

    state: str  # STATE_ON or STATE_OFF
    reason: Reason
    # Brightness (0-255) of dimmable lights that go back to a known level.
    brightness: dict[str, int] = field(default_factory=dict)
    attempts: int = 0
    failed: bool = False  # a failure was recorded: record the success too
    warned: bool = False


@dataclass(slots=True)
class Measurement:
    """A contribution measurement in progress: lights switched together."""

    turned_on: bool
    started: datetime
    context_id: str | None
    before: float | None
    members: dict[str, float] = field(default_factory=dict)  # light -> fraction


class RoomEngine:
    """Switches the lights of one room."""

    def __init__(
        self,
        hass: HomeAssistant,
        parent: BrightRoomsEngine,
        subentry_id: str,
        title: str,
        data: dict[str, Any],
    ) -> None:
        """Read the configuration."""
        self.hass = hass
        self.parent = parent
        self.subentry_id = subentry_id
        self.title = title
        self.data = dict(data)
        self.cfg = RoomConfig.from_data(self.data)
        self.enabled = True
        self.occupied: bool | None = None
        self.zone_occupied = False
        self.raw_lux: float | None = None
        self.ambient: int | None = None
        self.held = False
        self.dark: bool | None = None
        self.last_action: LastAction | None = None
        self._hold_until: datetime | None = None
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._pending_on = False
        self._seq: OffSequence | None = None
        self._bright_deadline: datetime | None = None
        self._measurement: Measurement | None = None
        self._goal: Goal | None = None
        self._reentry: Reentry | None = None
        # A light was turned off by someone else since the last arrival seen
        # (true at start: no arrival seen yet).
        self._off_by_someone_else = True
        self._startup_check = False
        self._last_change: dict[str, datetime] = {}
        self._own_contexts: deque[str] = deque(maxlen=64)
        self._expect: dict[str, tuple[str, datetime]] = {}
        self._unsub: CALLBACK_TYPE | None = None

    # ----------------------------------------------------------------- setup

    @callback
    def start(self) -> None:
        """Read the current states and start listening; nothing is switched."""
        now = dt_util.utcnow()
        self.occupied = self._occupancy()
        self.zone_occupied = self._zone()
        self.raw_lux = self._raw()
        self._update_ambient(now, initial=True)
        cfg = self.cfg
        watched = {
            *cfg.presence_sensors,
            *cfg.zone_sensors,
            *cfg.lights,
            *cfg.other_lights,
        }
        if cfg.illuminance_sensor:
            watched.add(cfg.illuminance_sensor)
        self._unsub = async_track_state_change_event(
            self.hass, sorted(watched), self._on_state
        )
        self._startup_check = True
        self._check_startup()
        self._schedule_band_refresh()

    @callback
    def stop(self) -> None:
        """Stop listening and cancel every timer (lights are left as they are)."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    # ---------------------------------------------------------------- timers

    def _schedule(self, name: str, delay: float, action: Callable[[], None]) -> None:
        self._cancel(name)
        if delay <= 0:
            action()
            return

        @callback
        def fire(_now: datetime) -> None:
            self._timers.pop(name, None)
            action()
            self.parent.notify(self)

        self._timers[name] = async_call_later(self.hass, delay, fire)

    def _cancel(self, name: str) -> None:
        if cancel := self._timers.pop(name, None):
            cancel()

    # ---------------------------------------------------------------- inputs

    def _occupancy(self) -> bool | None:
        states = [self.hass.states.get(e) for e in self.cfg.presence_sensors]
        valid = [s for s in states if _available(s)]
        if not valid:
            return None
        return any(s.state == STATE_ON for s in valid)

    def _zone(self) -> bool:
        return any(
            (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
            for e in self.cfg.zone_sensors
        )

    def _raw(self) -> float | None:
        if not self.cfg.illuminance_sensor:
            return None
        state = self.hass.states.get(self.cfg.illuminance_sensor)
        return parse_lux(state.state) if state is not None else None

    def dimmable(self, entity_id: str, state: State | None = None) -> bool:
        """Whether a light supports brightness."""
        state = state or self.hass.states.get(entity_id)
        modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) if state else None
        if modes is None:
            entry = er.async_get(self.hass).async_get(entity_id)
            modes = (
                (entry.capabilities or {}).get(ATTR_SUPPORTED_COLOR_MODES)
                if entry
                else None
            )
        return brightness_supported(modes)

    def _reading(self, entity_id: str) -> LightReading:
        state = self.hass.states.get(entity_id)
        on = state is not None and state.state == STATE_ON
        return LightReading(
            available=_available(state),
            on=on,
            fraction=light_fraction(
                state.attributes.get(ATTR_BRIGHTNESS) if on and state else None,
                self.dimmable(entity_id, state),
            ),
            contribution=self.contribution(entity_id).value,
        )

    def _lights_on(self) -> list[str]:
        return [
            e
            for e in self.cfg.lights
            if (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
        ]

    def contribution(self, entity_id: str) -> Contribution:
        """A light's learned contribution."""
        return self.parent.store.contribution(self.subentry_id, entity_id)

    # ---------------------------------------------------------------- events

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        now = dt_util.utcnow()
        cfg = self.cfg
        if entity_id in cfg.lights:
            self._on_light(entity_id, old, new, event.context, now)
        elif entity_id in cfg.other_lights and _light_change(old, new):
            self._last_change[entity_id] = now
            self._drop_measurement(Rejection.OTHER_LIGHT_CHANGED)
        if entity_id == cfg.illuminance_sensor:
            self.raw_lux = parse_lux(new.state) if new is not None else None
            self._update_ambient(now)
        if entity_id in cfg.presence_sensors:
            self._on_presence(now)
        if entity_id in cfg.zone_sensors:
            self._on_zone(now)
        self.parent.notify(self)

    def _on_light(
        self,
        entity_id: str,
        old: State | None,
        new: State | None,
        context: Context | None,
        now: datetime,
    ) -> None:
        kind = _light_change(old, new)
        if kind is None:
            return
        prior = self._last_change.get(entity_id)
        self._last_change[entity_id] = now
        if kind == "switch" and old is not None and new is not None:
            self._measure_switch(entity_id, old, new, context, prior, now)
        elif self._measurement is not None:
            self._drop_measurement(
                Rejection.LIGHT_CHANGED
                if entity_id in self._measurement.members
                else Rejection.OTHER_LIGHT_CHANGED
            )
        if kind != "unavailable":
            self._start_hold(now)
        if kind in ("switch", "brightness") and not self._is_ours(
            entity_id, new, context, now
        ):
            if new is not None and new.state == STATE_OFF and self.occupied is True:
                self._off_by_someone_else = True
            self._changed_by_someone_else(now)
        if self._seq is not None and not self._lights_on():
            self._end_sequence()
        self._update_ambient(now)
        if kind == "available":
            self._on_light_back(entity_id)
        self._check_reentry(now)
        self._check_goal_reached(now)

    def _is_ours(
        self, entity_id: str, new: State | None, context: Context | None, now: datetime
    ) -> bool:
        if context is not None and context.id in self._own_contexts:
            return True
        # A turn-off still in flight when someone came back.
        r = self._reentry
        if (
            r is not None
            and r.in_flight
            and entity_id in r.lights
            and new is not None
            and new.state == STATE_OFF
        ):
            return True
        # A command that raised or reported late but took effect after all.
        if self._goal is not None and new is not None and new.state == self._goal.state:
            return True
        expected = self._expect.get(entity_id)
        return (
            expected is not None
            and new is not None
            and now <= expected[1]
            and new.state == expected[0]
        )

    def _changed_by_someone_else(self, now: datetime) -> None:
        # Someone is looking after the lights: no turn-off after a restart.
        self._end_startup_check()
        self._clear_goal()  # their choice wins
        self._reentry = None
        if self._seq is not None:
            # Someone took over: leave every light as it is now.
            self._end_sequence()
        if self._pending_on:
            self._cancel_pending_on()
            self._record(Action.SKIPPED_ON, Reason.CHANGED_BY_SOMEONE_ELSE, now)

    def _on_presence(self, now: datetime) -> None:
        previous, self.occupied = self.occupied, self._occupancy()
        if previous is False and self.occupied is True:
            self._end_startup_check()
            self._on_arrival(now)
        elif previous is True and self.occupied is False:
            self._end_startup_check()
            self._on_leave(now)
        else:
            if self.occupied is not True:
                self._cancel_pending_on()
            self._check_startup()
        self._check_goal_reason()

    # --------------------------------------------------------------- startup

    def _check_startup(self) -> None:
        """Wait until every presence sensor has been available for a while."""
        if not self._startup_check:
            return
        if not all(
            _available(self.hass.states.get(e)) for e in self.cfg.presence_sensors
        ):
            self._cancel("startup")
            return
        if "startup" not in self._timers:
            self._schedule("startup", STARTUP_GRACE, self._startup_done)

    def _end_startup_check(self) -> None:
        self._startup_check = False
        self._cancel("startup")

    @callback
    def _startup_done(self) -> None:
        """Found empty with lights on after a start: turn off as usual."""
        self._startup_check = False
        if self.occupied is False and self._seq is None:
            self._on_leave(dt_util.utcnow())

    def _on_zone(self, now: datetime) -> None:
        self.zone_occupied = self._zone()
        seq = self._seq
        if seq is None or seq.phase == "dimmed":
            return
        if (
            seq.phase == "zone"
            and not self.zone_occupied
            or seq.phase == "empty"
            and self.zone_occupied
            and not seq.zone_timed_out
        ):
            self._sequence_wait(now)

    # --------------------------------------------------------------- turn on

    def _on_arrival(self, now: datetime) -> None:
        self._off_by_someone_else = False
        r = self._reentry
        if r is not None and self.enabled and now <= r.until:
            if r.in_flight:
                # Decided when the turn-off completes (_check_reentry).
                r.arrived = True
            else:
                self._restore_reentry()
            return
        self._reentry = None
        if self._seq is not None:
            self._cancel_sequence(now, restore=True)
            return
        if not self.enabled:
            self._record(Action.SKIPPED_ON, Reason.DISABLED, now)
            return
        self._pending_on = True
        self._schedule("on", self.cfg.on_delay, self._try_turn_on)

    def _cancel_pending_on(self) -> None:
        self._pending_on = False
        self._cancel("on")

    def _on_became_dark(self) -> None:
        """Dark arrived with people already in the room: as if they came in now.

        No `on_delay` (the room is already occupied); only when every
        available light is off, so lights turned off by hand stay off.
        """
        cfg = self.cfg
        if (
            not (self.enabled and cfg.on_when_dark and cfg.only_when_dark)
            or self.occupied is not True
            or self._pending_on
            or self._seq is not None
        ):
            return
        states = [self.hass.states.get(e) for e in cfg.lights]
        available = [s for s in states if s is not None and _available(s)]
        if not available or any(s.state == STATE_ON for s in available):
            return
        self._pending_on = True
        self._schedule("on", 0, lambda: self._try_turn_on(Reason.BECAME_DARK))

    @callback
    def _try_turn_on(self, reason: Reason | None = None) -> None:
        """Turn the lights on if the room still wants them.

        `reason` None: someone came in (skips are recorded); otherwise the
        reason of the turn-on, and a skip is silent.
        """
        now = dt_util.utcnow()
        self._pending_on = False
        if not self.enabled or self.occupied is not True:
            return
        states = {e: self.hass.states.get(e) for e in self.cfg.lights}
        available = [e for e, s in states.items() if _available(s)]
        if not available:
            # Every light is unavailable: turn them on when they come back.
            if self.cfg.lights and not (self.cfg.only_when_dark and self.dark is False):
                self._goal = Goal(STATE_ON, reason or self._presence_reason())
            return
        if any(states[e].state == STATE_ON for e in available):  # type: ignore[union-attr]
            if reason is None:
                self._record(Action.SKIPPED_ON, Reason.LIGHTS_ALREADY_ON, now)
            return
        if self.cfg.only_when_dark and self.dark is False:
            if reason is None:
                self._record(Action.SKIPPED_ON, Reason.NOT_DARK, now)
            return
        ready = max(states[e].last_changed for e in available) + timedelta(  # type: ignore[union-attr]
            seconds=self.cfg.min_off_seconds
        )
        if ready > now:
            # Lamps that change tint when switched quickly: wait, then check again.
            self._pending_on = True
            self._schedule(
                "on", (ready - now).total_seconds(), lambda: self._try_turn_on(reason)
            )
            return
        self._turn_on(available, now, reason)

    def _presence_reason(self) -> Reason:
        return (
            Reason.PRESENCE_DARK if self.cfg.only_when_dark else Reason.PRESENCE_ALWAYS
        )

    def _turn_on(
        self, lights: list[str], now: datetime, reason: Reason | None = None
    ) -> None:
        reason = reason or self._presence_reason()
        self._set_goal(Goal(STATE_ON, reason), lights)
        self._record(Action.TURNED_ON, reason, now)

    # -------------------------------------------------------------- turn off

    def _on_leave(self, now: datetime) -> None:
        self._cancel_pending_on()
        if self._reentry is not None:
            self._reentry.arrived = False  # gone again before the lights went off
        if not self.enabled or not self._lights_on():
            return
        self._seq = OffSequence()
        self._sequence_wait(now)

    def _sequence_wait(self, now: datetime) -> None:
        """Zone wait while a zone sensor is on (within its limit), then empty wait."""
        seq = self._seq
        assert seq is not None
        empty_wait, zone_wait = self.effective(now)
        if self.zone_occupied and not seq.zone_timed_out:
            if seq.zone_until is None:
                seq.zone_until = now + timedelta(seconds=zone_wait)
            if seq.zone_until > now:
                seq.phase = "zone"
                seq.deadline = seq.zone_until
                self._schedule(
                    "seq", (seq.zone_until - now).total_seconds(), self._zone_timeout
                )
                return
            seq.zone_timed_out = True
        seq.phase = "empty"
        seq.deadline = now + timedelta(seconds=empty_wait)
        self._schedule("seq", empty_wait, self._sequence_dim)

    @callback
    def _zone_timeout(self) -> None:
        if self._seq is None:
            return
        self._seq.zone_timed_out = True
        self._sequence_wait(dt_util.utcnow())

    @callback
    def _sequence_dim(self) -> None:
        seq = self._seq
        if seq is None:
            return
        now = dt_util.utcnow()
        on = self._lights_on()
        if not on:
            self._end_sequence()
            return
        cfg = self.cfg
        if cfg.dim_percent < 100 and cfg.dim_wait > 0:
            for entity_id in on:
                state = self.hass.states.get(entity_id)
                brightness = state.attributes.get(ATTR_BRIGHTNESS) if state else None
                if not self.dimmable(entity_id, state) or not brightness:
                    continue
                seq.remembered[entity_id] = int(brightness)
                target = max(1, round(brightness * cfg.dim_percent / 100))
                self._call(
                    SERVICE_TURN_ON,
                    [entity_id],
                    {ATTR_BRIGHTNESS: target, ATTR_TRANSITION: DIM_TRANSITION},
                )
        if seq.remembered:
            seq.phase = "dimmed"
            seq.deadline = now + timedelta(seconds=cfg.dim_wait)
            self._record(Action.DIMMED, self._off_reason(seq), now)
            self._schedule("seq", cfg.dim_wait, self._sequence_off)
            return
        self._sequence_off()

    @callback
    def _sequence_off(self) -> None:
        seq = self._seq
        if seq is None:
            return
        self._end_sequence()
        now = dt_util.utcnow()
        lights: dict[str, int | None] = {}
        for entity_id in self._lights_on():
            state = self.hass.states.get(entity_id)
            brightness = state.attributes.get(ATTR_BRIGHTNESS) if state else None
            if entity_id in seq.remembered:
                brightness = seq.remembered[entity_id]
            lights[entity_id] = (
                int(brightness) if brightness and self.dimmable(entity_id) else None
            )
        if lights:
            # In flight at most as long as the command is retried.
            self._reentry = Reentry(
                lights,
                now
                + timedelta(
                    seconds=REENTRY_SECONDS + GOAL_RETRY_SECONDS * GOAL_ATTEMPTS
                ),
            )
        self._turn_off(self._off_reason(seq), now)

    @staticmethod
    def _off_reason(seq: OffSequence) -> Reason:
        return Reason.ZONE_TIMEOUT if seq.zone_timed_out else Reason.EMPTY

    def _end_sequence(self) -> None:
        self._seq = None
        self._cancel("seq")

    def _cancel_sequence(self, now: datetime, restore: bool) -> None:
        """Someone is back: dimmed lights go back to their brightness."""
        seq = self._seq
        self._end_sequence()
        if not restore or seq is None or seq.phase != "dimmed":
            return
        restored = False
        for entity_id, brightness in seq.remembered.items():
            state = self.hass.states.get(entity_id)
            if state is None or state.state != STATE_ON:
                continue
            self._call(
                SERVICE_TURN_ON,
                [entity_id],
                {ATTR_BRIGHTNESS: brightness, ATTR_TRANSITION: DIM_TRANSITION},
            )
            restored = True
        if restored:
            self._record(Action.RESTORED, Reason.PRESENCE_BACK, now)

    def _turn_off(self, reason: Reason, now: datetime) -> None:
        on = self._lights_on()
        if not on:
            return
        self._set_goal(Goal(STATE_OFF, reason), on)
        self._record(Action.TURNED_OFF, reason, now)

    @callback
    def _bright_off(self) -> None:
        self._bright_deadline = None
        if not self.enabled or not self.cfg.off_when_bright or self.dark is not False:
            return
        self._cancel_pending_on()
        self._end_sequence()
        self._reentry = None
        self._turn_off(Reason.BRIGHT, dt_util.utcnow())

    # --------------------------------------------------------------- ambient

    def _start_hold(self, now: datetime) -> None:
        settle = float(self.parent.settings[CONF_SETTLE_SECONDS])
        self._hold_until = now + timedelta(seconds=settle)

        def release() -> None:
            self._update_ambient(dt_util.utcnow())

        self._schedule("hold", settle, release)

    def _update_ambient(self, now: datetime, initial: bool = False) -> None:
        readings = [self._reading(e) for e in self.cfg.lights]
        holding = self._hold_until is not None and now < self._hold_until
        if self.raw_lux is None:
            self.ambient, self.held = None, False
        elif holding or must_hold(readings):
            self.held = True
        else:
            self.ambient = ambient_light(self.raw_lux, own_light(readings))
            self.held = False
        previous = self.dark
        self.dark = next_dark(
            previous, self.ambient, self.cfg.dark_below, self.cfg.bright_above
        )
        if initial:
            return
        if previous is True and self.dark is False:
            if self.enabled and self.cfg.off_when_bright:
                self._bright_deadline = now + timedelta(minutes=self.cfg.bright_minutes)
                self._schedule("bright", self.cfg.bright_minutes * 60, self._bright_off)
        elif self.dark is not False and self._bright_deadline is not None:
            self._bright_deadline = None
            self._cancel("bright")
        if previous is False and self.dark is True:
            self._on_became_dark()
        if previous != self.dark:
            self._check_goal_reason()

    # -------------------------------------------------------------- learning

    def _may_measure(self, old: State, prior: datetime | None, now: datetime) -> bool:
        """The light was unchanged long enough before this change."""
        settings = self.parent.settings
        lasted = (now - old.last_updated).total_seconds()
        quiet_since = now - timedelta(seconds=LEARN_QUIET_BEFORE)
        return lasted >= float(settings[CONF_LEARN_MIN_PREVIOUS]) and (
            prior is None or prior < quiet_since
        )

    def _measure_switch(
        self,
        entity_id: str,
        old: State,
        new: State,
        context: Context | None,
        prior: datetime | None,
        now: datetime,
    ) -> None:
        """A light switched on or off: join the group being measured, or start one."""
        turned_on = new.state == STATE_ON
        lit = new if turned_on else old
        fraction = light_fraction(
            lit.attributes.get(ATTR_BRIGHTNESS), self.dimmable(entity_id, lit)
        )
        m = self._measurement
        if m is not None:
            together = (now - m.started).total_seconds() <= LEARN_GROUP_SECONDS or (
                context is not None and context.id == m.context_id
            )
            if entity_id not in m.members and m.turned_on == turned_on and together:
                if not self._may_measure(old, prior, now):
                    self._drop_measurement(Rejection.LIGHT_CHANGED)
                    return
                m.members[entity_id] = fraction
                self._schedule_measurement()
                return
            # Switched again, or another light on its own: not measurable.
            self._drop_measurement(
                None if entity_id in m.members else Rejection.OTHER_LIGHT_CHANGED
            )
        if not self.cfg.illuminance_sensor or not self._may_measure(old, prior, now):
            return
        quiet_since = now - timedelta(seconds=LEARN_QUIET_BEFORE)
        if any(
            at >= quiet_since
            for other, at in self._last_change.items()
            if other != entity_id
        ):
            _LOGGER.debug(
                "%s: %s not measured: %s",
                self.title,
                entity_id,
                Rejection.OTHER_LIGHT_CHANGED,
            )
            return
        self._measurement = Measurement(
            turned_on=turned_on,
            started=now,
            context_id=context.id if context is not None else None,
            before=self.raw_lux,
            members={entity_id: fraction},
        )
        self._schedule_measurement()

    def _schedule_measurement(self) -> None:
        self._schedule(
            "measure",
            float(self.parent.settings[CONF_SETTLE_SECONDS]),
            self._finish_measurement,
        )

    def _drop_measurement(self, why: Rejection | None) -> None:
        m, self._measurement = self._measurement, None
        self._cancel("measure")
        if m is not None and why is not None:
            _LOGGER.debug("%s: %s not measured: %s", self.title, list(m.members), why)

    @callback
    def _finish_measurement(self) -> None:
        m, self._measurement = self._measurement, None
        if m is None:
            return
        lights = list(m.members)
        current = [self.contribution(e) for e in lights]
        settings = self.parent.settings
        result = measure_group(
            turned_on=m.turned_on,
            before=m.before,
            after=self.raw_lux,
            others=own_light(
                self._reading(e) for e in self.cfg.lights if e not in m.members
            ),
            members=[
                Member(m.members[e], c.value)
                for e, c in zip(lights, current, strict=True)
            ],
            ambient_max=float(settings[CONF_LEARN_AMBIENT_MAX]),
            weight=float(settings[CONF_LEARN_WEIGHT]),
        )
        if isinstance(result, Rejection):
            _LOGGER.debug("%s: %s not measured: %s", self.title, lights, result)
            return
        now = dt_util.utcnow()
        for entity_id, c, value in zip(lights, current, result, strict=True):
            if value is None:
                continue
            _LOGGER.debug(
                "%s: %s contribution %s -> %s", self.title, entity_id, c.value, value
            )
            self.parent.store.set_contribution(
                self.subentry_id,
                entity_id,
                Contribution(value, c.samples + 1, _iso(now)),
            )
        self._update_ambient(now)

    # ------------------------------------------------------------- commands

    def _call(
        self,
        service: str,
        lights: list[str],
        data: dict[str, Any],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Send a light command with Bright Rooms' own context."""
        context = Context()
        self._own_contexts.append(context.id)
        expected = STATE_ON if service == SERVICE_TURN_ON else STATE_OFF
        until = dt_util.utcnow() + timedelta(
            seconds=EXPECT_SECONDS + float(data.get(ATTR_TRANSITION, 0))
        )
        for entity_id in lights:
            self._expect[entity_id] = (expected, until)
        self.hass.async_create_task(
            self._async_call(
                service, {ATTR_ENTITY_ID: lights, **data}, context, on_error
            ),
            eager_start=False,
        )

    async def _async_call(
        self,
        service: str,
        data: dict[str, Any],
        context: Context,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN, service, data, blocking=True, context=context
            )
        except HomeAssistantError as err:
            _LOGGER.debug("%s: light.%s failed: %s", self.title, service, err)
            if on_error is not None:
                on_error(str(err) or type(err).__name__)
                self.parent.notify(self)

    def _record(
        self, action: Action, reason: Reason, now: datetime, detail: str | None = None
    ) -> None:
        self.last_action = LastAction(action, reason, now, detail)

    # -------------------------------------------------------------- re-entry

    def _check_reentry(self, now: datetime) -> None:
        """The turn-off in flight completed: open the window, or turn back on."""
        r = self._reentry
        if r is None or not r.in_flight:
            return
        if any(
            (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
            for e in r.lights
        ):
            return
        r.in_flight = False
        r.until = now + timedelta(seconds=REENTRY_SECONDS)
        if r.arrived and self.occupied is True:
            self._restore_reentry()

    def _restore_reentry(self) -> None:
        """Someone came back right after the lights went off: back as they were."""
        r, self._reentry = self._reentry, None
        if r is None:
            return
        states = {e: self.hass.states.get(e) for e in r.lights}
        lights = [
            e for e, s in states.items() if s is not None and s.state == STATE_OFF
        ]
        if not lights:
            return
        ready = max(states[e].last_changed for e in lights) + timedelta(  # type: ignore[union-attr]
            seconds=self.cfg.min_off_seconds
        )
        self._cancel_pending_on()
        self._pending_on = True

        def turn_on() -> None:
            self._pending_on = False
            if not self.enabled or self.occupied is not True:
                return
            off = [
                e
                for e in lights
                if (s := self.hass.states.get(e)) is not None and s.state == STATE_OFF
            ]
            if not off:
                return
            goal = Goal(
                STATE_ON,
                Reason.PRESENCE_BACK,
                brightness={e: b for e, b in r.lights.items() if b is not None},
            )
            self._set_goal(goal, off)
            self._record(Action.TURNED_ON, Reason.PRESENCE_BACK, dt_util.utcnow())

        self._schedule("on", (ready - dt_util.utcnow()).total_seconds(), turn_on)

    # ---------------------------------------------------------------- bands

    def active_band(self, now: datetime | None = None) -> Band | None:
        """The room's time band active now, if any."""
        return active_band(self.cfg.schedule, dt_util.as_local(now or dt_util.utcnow()))

    def effective(self, now: datetime | None = None) -> tuple[int, int]:
        """Empty wait and zone wait now (a band may override them)."""
        band = self.active_band(now)
        empty = int(self.cfg.empty_wait)
        zone = int(self.cfg.zone_wait)
        if band is not None:
            empty = band.empty_wait if band.empty_wait is not None else empty
            zone = band.zone_wait if band.zone_wait is not None else zone
        return empty, zone

    def _schedule_band_refresh(self) -> None:
        """Update the entities and the panel when a band starts or ends."""
        now = dt_util.as_local(dt_util.utcnow())
        at = next_boundary(self.cfg.schedule, now)
        if at is not None:
            self._schedule(
                "band", (at - now).total_seconds(), self._schedule_band_refresh
            )

    # ----------------------------------------------------------------- goals

    def _set_goal(self, goal: Goal, lights: list[str]) -> None:
        """Command the lights towards a new goal; check and retry later."""
        self._goal = goal
        self._send_goal(goal, lights)

    def _send_goal(self, goal: Goal, lights: list[str]) -> None:
        goal.attempts += 1

        @callback
        def failed(detail: str) -> None:
            if self._goal is not goal:
                return
            goal.failed = True
            self._record(Action.FAILED, goal.reason, dt_util.utcnow(), detail)

        dimmable = [e for e in lights if self.dimmable(e)]
        plain = [e for e in lights if e not in dimmable]
        cfg = self.cfg
        if goal.state == STATE_ON:
            for entity_id in [e for e in dimmable if e in goal.brightness]:
                dimmable.remove(entity_id)
                self._call(
                    SERVICE_TURN_ON,
                    [entity_id],
                    {ATTR_BRIGHTNESS: goal.brightness[entity_id]},
                    failed,
                )
            if plain:
                self._call(SERVICE_TURN_ON, plain, {}, failed)
            if dimmable:
                pct = brightness_pct(
                    self.ambient,
                    cfg.brightness_min,
                    cfg.brightness_dark_lux,
                    cfg.brightness_full_lux,
                )
                self._call(
                    SERVICE_TURN_ON, dimmable, {ATTR_BRIGHTNESS_PCT: pct}, failed
                )
        else:
            if plain:
                self._call(SERVICE_TURN_OFF, plain, {}, failed)
            if dimmable:
                data = {ATTR_TRANSITION: cfg.transition} if cfg.transition else {}
                self._call(SERVICE_TURN_OFF, dimmable, data, failed)
        self._schedule("goal", GOAL_RETRY_SECONDS, self._goal_retry)

    def _goal_reached(self, goal: Goal) -> bool:
        return all(
            (s := self.hass.states.get(e)) is not None and s.state == goal.state
            for e in self.cfg.lights
        )

    def _check_goal_reached(self, now: datetime) -> None:
        goal = self._goal
        if goal is None or not self._goal_reached(goal):
            return
        self._clear_goal()
        if goal.failed:
            # Done after all (a retry, or a command that worked but raised).
            action = Action.TURNED_ON if goal.state == STATE_ON else Action.TURNED_OFF
            self._record(action, goal.reason, now)

    @callback
    def _goal_retry(self) -> None:
        """Send the goal again to the available lights that did not follow."""
        goal = self._goal
        if goal is None:
            return
        now = dt_util.utcnow()
        self._check_goal_reached(now)
        if self._goal is not goal:
            return
        behind = [
            e
            for e in self.cfg.lights
            if _available(s := self.hass.states.get(e)) and s.state != goal.state  # type: ignore[union-attr]
        ]
        if not behind:
            return  # only unavailable lights left: done when they come back
        if goal.attempts >= GOAL_ATTEMPTS:
            if not goal.warned:
                goal.warned = True
                _LOGGER.warning(
                    "%s: %s did not turn %s after %s attempts",
                    self.title,
                    ", ".join(behind),
                    goal.state,
                    goal.attempts,
                )
                if not goal.failed:
                    goal.failed = True
                    self._record(Action.FAILED, goal.reason, now, "no response")
            return
        self._send_goal(goal, behind)

    def _clear_goal(self) -> None:
        self._goal = None
        self._cancel("goal")
        for name in [n for n in self._timers if n.startswith("back:")]:
            self._cancel(name)

    def _check_goal_reason(self) -> None:
        """Drop the goal when the reason for it no longer holds."""
        goal = self._goal
        if goal is None:
            return
        if goal.state == STATE_ON:
            if self.occupied is not True or (
                self.cfg.only_when_dark and self.dark is False
            ):
                self._clear_goal()
        elif goal.reason is Reason.BRIGHT:
            if self.dark is True:
                self._clear_goal()
        elif self.occupied is True:
            self._clear_goal()

    def _on_light_back(self, entity_id: str) -> None:
        """A light is available again: give it the goal, or catch up on an arrival."""
        if not self.enabled:
            return
        goal = self._goal
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        if goal is not None:
            if state.state == goal.state:
                return
            delay = 0.0
            if goal.state == STATE_ON:
                ready = state.last_changed + timedelta(seconds=self.cfg.min_off_seconds)
                delay = (ready - dt_util.utcnow()).total_seconds()
            self._schedule(
                f"back:{entity_id}", delay, lambda: self._apply_back(entity_id)
            )
            return
        cfg = self.cfg
        if (
            self.occupied is not True
            or self._off_by_someone_else
            or self._pending_on
            or self._seq is not None
            or (cfg.only_when_dark and self.dark is False)
            or self._lights_on()
        ):
            return
        # Someone came in while the lights were unavailable.
        self._pending_on = True
        self._schedule("on", 0, lambda: self._try_turn_on(Reason.LIGHT_BACK))

    @callback
    def _apply_back(self, entity_id: str) -> None:
        goal = self._goal
        state = self.hass.states.get(entity_id)
        if goal is None or not _available(state) or state.state == goal.state:  # type: ignore[union-attr]
            return
        # From now on the goal is about this light coming back.
        goal.reason = Reason.LIGHT_BACK
        goal.attempts = 0
        goal.failed = goal.warned = False
        self._send_goal(goal, [entity_id])
        action = Action.TURNED_ON if goal.state == STATE_ON else Action.TURNED_OFF
        self._record(action, Reason.LIGHT_BACK, dt_util.utcnow())

    # ---------------------------------------------------------------- public

    def set_enabled(self, enabled: bool) -> None:
        """Automatic switch: disabling cancels everything, lights stay as they are."""
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if not enabled:
            self._clear_goal()
            self._reentry = None
            self._cancel_pending_on()
            self._end_sequence()
            self._bright_deadline = None
            self._cancel("bright")
        self.parent.store.set_enabled(self.subentry_id, enabled)
        self.parent.notify(self)

    def contribution_changed(self) -> None:
        """A contribution was set by hand."""
        self._update_ambient(dt_util.utcnow())
        self.parent.notify(self)

    @property
    def status(self) -> Status:
        """What the room is doing."""
        if not self.enabled:
            return Status.DISABLED
        if self._seq is not None:
            return Status.DIMMED if self._seq.phase == "dimmed" else Status.WAITING
        return Status.ON if self._lights_on() else Status.OFF

    @property
    def deadline(self) -> datetime | None:
        """Next timed step: end of the wait or of the dimming, or the bright timer."""
        times = []
        if self._seq is not None and self._seq.deadline is not None:
            times.append(self._seq.deadline)
        if self._bright_deadline is not None and self._lights_on():
            times.append(self._bright_deadline)
        return min(times) if times else None

    @property
    def name(self) -> str:
        """The room's name (its area's for rooms saved without one)."""
        return room_title(self.hass, self.data, self.title)

    def sensor_entities(self) -> list[str]:
        """Settings of the presence sensors' devices (sensitivity, delays…)."""
        registry = er.async_get(self.hass)
        devices = {
            entry.device_id
            for e in self.cfg.presence_sensors
            if (entry := registry.async_get(e)) is not None and entry.device_id
        }
        found: set[str] = set()
        for device_id in devices:
            for entry in er.async_entries_for_device(registry, device_id):
                if (
                    entry.entity_category is EntityCategory.CONFIG
                    and entry.domain in SENSOR_SETTING_DOMAINS
                    and entry.disabled_by is None
                ):
                    found.add(entry.entity_id)
        return sorted(found)

    def snapshot(self) -> dict[str, Any]:
        """Everything the panel shows about the room, JSON-ready."""
        lights = []
        for entity_id in self.cfg.lights:
            state = self.hass.states.get(entity_id)
            contribution = self.contribution(entity_id)
            brightness = state.attributes.get(ATTR_BRIGHTNESS) if state else None
            lights.append(
                {
                    "entity_id": entity_id,
                    "name": state.name if state else entity_id,
                    "state": state.state if state else STATE_UNAVAILABLE,
                    "brightness": int(brightness)
                    if state and state.state == STATE_ON and brightness is not None
                    else None,
                    "dimmable": self.dimmable(entity_id, state),
                    "contribution": contribution.value,
                    "samples": contribution.samples,
                    "updated": contribution.updated,
                }
            )
        return {
            "id": self.subentry_id,
            "name": self.name,
            "area_id": self.cfg.area_id,
            "enabled": self.enabled,
            "config": {**room_config(self.data), CONF_NAME: self.name},
            "status": self.status.value,
            "occupied": self.occupied,
            "zone_occupied": self.zone_occupied,
            "raw_lux": self.raw_lux,
            "ambient": self.ambient,
            "held": self.held,
            "dark": self.dark,
            "deadline": _iso(self.deadline),
            "last_action": self.last_action.as_dict() if self.last_action else None,
            "goal": self._goal.state if self._goal else None,
            "active_band": band.id if (band := self.active_band()) else None,
            "effective": dict(
                zip(("empty_wait", "zone_wait"), self.effective(), strict=True)
            ),
            "lights": lights,
            "sensor_entities": self.sensor_entities(),
        }


def _light_change(old: State | None, new: State | None) -> str | None:
    """How a light changed: switch, brightness, available, unavailable or None."""
    if new is None or new.state in _BAD:
        return "unavailable" if old is not None and old.state not in _BAD else None
    if old is None or old.state in _BAD:
        return "available"
    if old.state != new.state:
        return "switch" if {old.state, new.state} == {STATE_ON, STATE_OFF} else None
    if new.state == STATE_ON and old.attributes.get(
        ATTR_BRIGHTNESS
    ) != new.attributes.get(ATTR_BRIGHTNESS):
        return "brightness"
    return None


class BrightRoomsEngine:
    """The rooms of the entry, their saved state and the global settings."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Read the configuration."""
        self.hass = hass
        self.entry = entry
        self.settings = settings(entry)
        self.store = BrightRoomsStore(hass, entry.entry_id)
        self.device_id: str | None = None  # set by async_setup_entry
        self.running = False  # between async_start and async_stop
        self.rooms: dict[str, RoomEngine] = {
            sub.subentry_id: RoomEngine(
                hass, self, sub.subentry_id, sub.title, dict(sub.data)
            )
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_ROOM
        }

    @property
    def signal(self) -> str:
        """Dispatcher signal sent when anything changes."""
        return update_signal(self.entry.entry_id)

    async def async_start(self) -> None:
        """Load the saved state and start the rooms."""
        await self.store.async_load(
            {room_id: list(r.cfg.lights) for room_id, r in self.rooms.items()}
        )
        for room_id, room in self.rooms.items():
            room.enabled = self.store.enabled(room_id)
            room.start()
        self.running = True
        async_dispatcher_send(self.hass, self.signal)

    async def async_stop(self) -> None:
        """Stop the rooms and save."""
        self.running = False
        for room in self.rooms.values():
            room.stop()
        await self.store.async_save()

    @callback
    def notify(self, room: RoomEngine) -> None:
        """A room changed: entities and panel subscriptions update."""
        async_dispatcher_send(self.hass, room_signal(room.subentry_id))
        async_dispatcher_send(self.hass, self.signal)

    def set_room_enabled(self, room_id: str, enabled: bool) -> None:
        """Automatic switch of a room."""
        self.rooms[room_id].set_enabled(enabled)

    def set_contribution(
        self, room_id: str, entity_id: str, value: float | None
    ) -> None:
        """Set a contribution by hand; None forgets it (learned again)."""
        room = self.rooms[room_id]
        contribution = (
            Contribution()
            if value is None
            else Contribution(
                round(value),
                room.contribution(entity_id).samples,
                _iso(dt_util.utcnow()),
            )
        )
        self.store.set_contribution(room_id, entity_id, contribution)
        room.contribution_changed()

    def snapshot(self) -> dict[str, Any]:
        """Everything the panel shows, JSON-ready (rooms by area name)."""
        rooms = sorted(self.rooms.values(), key=lambda r: r.name.casefold())
        return {
            "entry_id": self.entry.entry_id,
            "settings": dict(self.settings),
            "rooms": [r.snapshot() for r in rooms],
        }
