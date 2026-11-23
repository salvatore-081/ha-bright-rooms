"""Constants for Bright Rooms."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "bright_rooms"
TITLE: Final = "Bright Rooms"

SUBENTRY_ROOM: Final = "room"

STORAGE_VERSION: Final = 1

# Options (global settings)
CONF_SETTLE_SECONDS: Final = "settle_seconds"
CONF_LEARN_AMBIENT_MAX: Final = "learn_ambient_max"
CONF_LEARN_MIN_PREVIOUS: Final = "learn_min_previous"
CONF_LEARN_WEIGHT: Final = "learn_weight"

SETTINGS_DEFAULTS: Final[dict[str, float]] = {
    CONF_SETTLE_SECONDS: 75,
    CONF_LEARN_AMBIENT_MAX: 60,
    CONF_LEARN_MIN_PREVIOUS: 90,
    CONF_LEARN_WEIGHT: 0.2,
}

# Room subentry
CONF_AREA: Final = "area"
CONF_PRESENCE_SENSORS: Final = "presence_sensors"
CONF_ZONE_SENSORS: Final = "zone_sensors"
CONF_LIGHTS: Final = "lights"
CONF_ILLUMINANCE_SENSOR: Final = "illuminance_sensor"
CONF_OTHER_LIGHTS: Final = "other_lights"
CONF_ON_DELAY: Final = "on_delay"
CONF_ONLY_WHEN_DARK: Final = "only_when_dark"
CONF_DARK_BELOW: Final = "dark_below"
CONF_BRIGHT_ABOVE: Final = "bright_above"
CONF_OFF_WHEN_BRIGHT: Final = "off_when_bright"
CONF_BRIGHT_MINUTES: Final = "bright_minutes"
CONF_MIN_OFF_SECONDS: Final = "min_off_seconds"
CONF_BRIGHTNESS_MIN: Final = "brightness_min"
CONF_BRIGHTNESS_DARK_LUX: Final = "brightness_dark_lux"
CONF_BRIGHTNESS_FULL_LUX: Final = "brightness_full_lux"
CONF_EMPTY_WAIT: Final = "empty_wait"
CONF_ZONE_WAIT: Final = "zone_wait"
CONF_DIM_PERCENT: Final = "dim_percent"
CONF_DIM_WAIT: Final = "dim_wait"
CONF_TRANSITION: Final = "transition"

ROOM_DEFAULTS: Final[dict[str, object]] = {
    CONF_ON_DELAY: 0,
    CONF_ONLY_WHEN_DARK: True,
    CONF_DARK_BELOW: 40,
    CONF_BRIGHT_ABOVE: 80,
    CONF_OFF_WHEN_BRIGHT: True,
    CONF_BRIGHT_MINUTES: 10,
    CONF_MIN_OFF_SECONDS: 0,
    CONF_BRIGHTNESS_MIN: 100,
    CONF_BRIGHTNESS_DARK_LUX: 10,
    CONF_BRIGHTNESS_FULL_LUX: 200,
    CONF_EMPTY_WAIT: 30,
    CONF_ZONE_WAIT: 150,
    CONF_DIM_PERCENT: 30,
    CONF_DIM_WAIT: 10,
    CONF_TRANSITION: 3,
}

# Transition of the dimming warning and of the restore (seconds).
DIM_TRANSITION: Final = 2
# Changes of other lights this long before a light changes spoil its measurement.
LEARN_QUIET_BEFORE: Final = 30
# Smallest jump of the illuminance sensor that counts as a measurement (lx).
LEARN_MIN_JUMP: Final = 5
# Lights switched in the same direction this close together (or with the same
# context) are measured as one group.
LEARN_GROUP_SECONDS: Final = 2
# After a start, an empty room with lights on is turned off once every
# presence sensor has been available for this long.
STARTUP_GRACE: Final = 30


class Status(StrEnum):
    """What a room is doing."""

    DISABLED = "disabled"
    OFF = "off"
    ON = "on"
    WAITING = "waiting"
    DIMMED = "dimmed"


class Action(StrEnum):
    """Last action of a room."""

    TURNED_ON = "turned_on"
    TURNED_OFF = "turned_off"
    DIMMED = "dimmed"
    RESTORED = "restored"
    SKIPPED_ON = "skipped_on"


class Reason(StrEnum):
    """Why an action was taken."""

    PRESENCE_DARK = "presence_dark"
    PRESENCE_ALWAYS = "presence_always"
    BRIGHT = "bright"
    EMPTY = "empty"
    ZONE_TIMEOUT = "zone_timeout"
    PRESENCE_BACK = "presence_back"
    CHANGED_BY_SOMEONE_ELSE = "changed_by_someone_else"
    NOT_DARK = "not_dark"
    LIGHTS_ALREADY_ON = "lights_already_on"
    DISABLED = "disabled"
