"""Form schemas and validation, shared by the config flows and the panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import selector

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
    CONF_ONLY_WHEN_DARK,
    CONF_OTHER_LIGHTS,
    CONF_PRESENCE_SENSORS,
    CONF_SETTLE_SECONDS,
    CONF_TRANSITION,
    CONF_ZONE_SENSORS,
    CONF_ZONE_WAIT,
    ROOM_DEFAULTS,
    SETTINGS_DEFAULTS,
    SUBENTRY_ROOM,
)

SENSORS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=BINARY_SENSOR_DOMAIN, multiple=True)
)
LIGHTS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=LIGHT_DOMAIN, multiple=True)
)

# Whole numbers (the number selector gives floats).
INT_FIELDS = {
    CONF_ON_DELAY,
    CONF_DARK_BELOW,
    CONF_BRIGHT_ABOVE,
    CONF_BRIGHT_MINUTES,
    CONF_MIN_OFF_SECONDS,
    CONF_BRIGHTNESS_MIN,
    CONF_BRIGHTNESS_DARK_LUX,
    CONF_BRIGHTNESS_FULL_LUX,
    CONF_EMPTY_WAIT,
    CONF_ZONE_WAIT,
    CONF_DIM_PERCENT,
    CONF_DIM_WAIT,
    CONF_TRANSITION,
    CONF_SETTLE_SECONDS,
    CONF_LEARN_AMBIENT_MAX,
    CONF_LEARN_MIN_PREVIOUS,
}


def _number(
    max_value: float,
    unit: str | None,
    min_value: float = 0,
    step: float = 1,
    mode: selector.NumberSelectorMode = selector.NumberSelectorMode.BOX,
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=min_value, max=max_value, step=step, mode=mode
    )
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _lux() -> selector.NumberSelector:
    return _number(100000, "lx")


def _percent() -> selector.NumberSelector:
    return _number(100, "%", min_value=1, mode=selector.NumberSelectorMode.SLIDER)


# ------------------------------------------------------------------ rooms


def room_schema() -> vol.Schema:
    """Fields of a room.

    Presence sensors and lights are optional here so that a missing value
    comes back as a translated error (`validate_room`), not as "invalid".
    """
    return vol.Schema(
        {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_AREA): selector.AreaSelector(),
            vol.Optional(CONF_PRESENCE_SENSORS): SENSORS_SELECTOR,
            vol.Optional(CONF_ZONE_SENSORS): SENSORS_SELECTOR,
            vol.Optional(CONF_LIGHTS): LIGHTS_SELECTOR,
            vol.Optional(CONF_ILLUMINANCE_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=SENSOR_DOMAIN, device_class="illuminance"
                )
            ),
            vol.Optional(CONF_OTHER_LIGHTS): LIGHTS_SELECTOR,
            vol.Required(CONF_ON_DELAY): _number(600, "s"),
            vol.Required(CONF_ONLY_WHEN_DARK): selector.BooleanSelector(),
            vol.Required(CONF_DARK_BELOW): _lux(),
            vol.Required(CONF_BRIGHT_ABOVE): _lux(),
            vol.Required(CONF_OFF_WHEN_BRIGHT): selector.BooleanSelector(),
            vol.Required(CONF_BRIGHT_MINUTES): _number(120, "min"),
            vol.Required(CONF_MIN_OFF_SECONDS): _number(60, "s"),
            vol.Required(CONF_BRIGHTNESS_MIN): _percent(),
            vol.Required(CONF_BRIGHTNESS_DARK_LUX): _lux(),
            vol.Required(CONF_BRIGHTNESS_FULL_LUX): _lux(),
            vol.Required(CONF_EMPTY_WAIT): _number(3600, "s"),
            vol.Required(CONF_ZONE_WAIT): _number(3600, "s"),
            vol.Required(CONF_DIM_PERCENT): _percent(),
            vol.Required(CONF_DIM_WAIT): _number(600, "s"),
            vol.Required(CONF_TRANSITION): _number(30, "s"),
        }
    )


def room_keys() -> list[str]:
    """Every field of the room form, in order."""
    return [str(key) for key in room_schema().schema]


def room_title(
    hass: HomeAssistant, data: dict[str, Any], fallback: str | None = None
) -> str:
    """A room's name; rooms saved without one are named after their area."""
    if name := str(data.get(CONF_NAME) or "").strip():
        return name
    area = ar.async_get(hass).async_get_area(data.get(CONF_AREA) or "")
    return area.name if area else fallback or str(data.get(CONF_AREA) or "")


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Whole numbers as int, empty optional fields left out."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if value in (None, "", []):
            continue
        if key in INT_FIELDS and isinstance(value, float) and value.is_integer():
            value = int(value)
        if key == CONF_NAME and isinstance(value, str):
            value = value.strip()
        out[key] = value
    return out


def normalize_room(data: dict[str, Any]) -> dict[str, Any]:
    """Room data to save: the form's values over the defaults."""
    return {**ROOM_DEFAULTS, **_clean(data)}


def room_config(data: dict[str, Any]) -> dict[str, Any]:
    """Every room setting, defaults included (the panel's `config`)."""
    return {
        CONF_PRESENCE_SENSORS: [],
        CONF_ZONE_SENSORS: [],
        CONF_LIGHTS: [],
        CONF_ILLUMINANCE_SENSOR: None,
        CONF_OTHER_LIGHTS: [],
        **ROOM_DEFAULTS,
        **{k: v for k, v in data.items() if k in room_keys()},
    }


def validate_room(
    hass: HomeAssistant, entry: ConfigEntry, data: dict[str, Any], current: str | None
) -> dict[str, str]:
    """Errors by field (translation keys), empty when the room is valid.

    Several rooms may share an area (two light groups with their own
    sensors); names must differ, ignoring case.
    """
    errors: dict[str, str] = {}
    data = normalize_room(data)
    name = room_title(hass, data).casefold()
    other_lights: set[str] = set()
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_ROOM or sub.subentry_id == current:
            continue
        if room_title(hass, dict(sub.data), sub.title).casefold() == name:
            errors[CONF_NAME] = "name_taken"
        other_lights.update(sub.data.get(CONF_LIGHTS) or [])
    if not data.get(CONF_PRESENCE_SENSORS):
        errors[CONF_PRESENCE_SENSORS] = "no_presence"
    if not data.get(CONF_LIGHTS):
        errors[CONF_LIGHTS] = "no_lights"
    elif other_lights.intersection(data[CONF_LIGHTS]):
        errors[CONF_LIGHTS] = "light_in_other_room"
    if data[CONF_BRIGHT_ABOVE] <= data[CONF_DARK_BELOW]:
        errors[CONF_BRIGHT_ABOVE] = "bright_not_above_dark"
    if data[CONF_BRIGHTNESS_FULL_LUX] <= data[CONF_BRIGHTNESS_DARK_LUX]:
        errors[CONF_BRIGHTNESS_FULL_LUX] = "brightness_lux_order"
    return errors


# --------------------------------------------------------------- settings


def settings_schema() -> vol.Schema:
    """Global settings (options of the entry)."""
    return vol.Schema(
        {
            vol.Required(CONF_SETTLE_SECONDS): _number(600, "s", min_value=5),
            vol.Required(CONF_LEARN_AMBIENT_MAX): _lux(),
            vol.Required(CONF_LEARN_MIN_PREVIOUS): _number(3600, "s"),
            vol.Required(CONF_LEARN_WEIGHT): _number(
                1,
                None,
                min_value=0.05,
                step=0.05,
                mode=selector.NumberSelectorMode.SLIDER,
            ),
        }
    )


def normalize_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Settings to save, over the defaults."""
    return {**SETTINGS_DEFAULTS, **_clean(data)}


def settings(entry: ConfigEntry) -> dict[str, Any]:
    """The entry's settings, defaults included."""
    keys = set(SETTINGS_DEFAULTS)
    return {
        **SETTINGS_DEFAULTS,
        **{k: v for k, v in entry.options.items() if k in keys},
    }
