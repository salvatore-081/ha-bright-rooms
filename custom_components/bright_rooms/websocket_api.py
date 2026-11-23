"""WebSocket API of the panel and of the card."""

from __future__ import annotations

import time
from functools import wraps
from types import MappingProxyType
from typing import Any

import probatio
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later

from .const import CONF_NAME, CONF_SCHEDULE, DOMAIN, ROOM_DEFAULTS, SUBENTRY_ROOM
from .engine import BrightRoomsEngine, update_signal
from .schedule import validate_schedule
from .schema import (
    normalize_room,
    normalize_settings,
    room_config,
    room_keys,
    room_schema,
    room_title,
    settings,
    settings_schema,
    validate_room,
)

# At most one snapshot per subscription in this many seconds.
THROTTLE = 0.5

ERR_NOT_FOUND = "not_found"
ERR_NOT_LOADED = "not_loaded"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the commands."""
    for command in (
        ws_rooms,
        ws_subscribe,
        ws_schema,
        ws_room_save,
        ws_room_delete,
        ws_room_set_enabled,
        ws_contribution_set,
        ws_settings_save,
    ):
        websocket_api.async_register_command(hass, command)


class _Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _entry(hass: HomeAssistant) -> ConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise _Error(ERR_NOT_FOUND, "Bright Rooms is not set up")
    return entries[0]


def _engine(hass: HomeAssistant) -> BrightRoomsEngine:
    entry = _entry(hass)
    if entry.state is not ConfigEntryState.LOADED:
        raise _Error(ERR_NOT_LOADED, "Bright Rooms is not loaded")
    return entry.runtime_data


def _room(entry: ConfigEntry, room_id: str) -> ConfigSubentry:
    sub = entry.subentries.get(room_id)
    if sub is None or sub.subentry_type != SUBENTRY_ROOM:
        raise _Error(ERR_NOT_FOUND, "Unknown room")
    return sub


def _handle(func):
    """Turn _Error and HomeAssistantError into WebSocket errors."""

    @wraps(func)
    async def wrapper(hass, connection, msg):
        try:
            await func(hass, connection, msg)
        except _Error as err:
            connection.send_error(msg["id"], err.code, str(err))
        except HomeAssistantError as err:
            code = getattr(err, "translation_key", None) or "error"
            connection.send_error(msg["id"], code, str(err))

    return wrapper


def _serialize(schema: vol.Schema) -> list[dict[str, Any]]:
    # Same serialization as the config flows (HA 2026.10 and later).
    return probatio.to_field_list(schema, custom_serializer=cv.custom_serializer)


def _field_errors(err: vol.Invalid) -> dict[str, str]:
    errors: dict[str, str] = {}
    for e in err.errors if isinstance(err, vol.MultipleInvalid) else [err]:
        field = str(e.path[0]) if e.path else "base"
        errors[field] = "invalid"
    return errors


def _form_data(raw: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Known fields only; a field cleared in the form may come as null or ""."""
    return {k: v for k, v in raw.items() if k in keys and v not in (None, "")}


# ------------------------------------------------------------------- read


@websocket_api.websocket_command({vol.Required("type"): "bright_rooms/rooms"})
@websocket_api.async_response
@_handle
async def ws_rooms(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The rooms and their live state."""
    connection.send_result(msg["id"], _engine(hass).snapshot())


@websocket_api.websocket_command({vol.Required("type"): "bright_rooms/subscribe"})
@websocket_api.async_response
@_handle
async def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send a snapshot now and after every change (throttled).

    Errors `not_found` (not set up) and `not_loaded` at subscription. While
    the entry reloads later (a room or the settings changed) nothing is sent:
    the new engine sends a snapshot when it starts.
    """
    # Not set up or not loaded: an error now, not a subscription that stays silent.
    entry_id = _engine(hass).entry.entry_id
    last_sent = 0.0
    timer: CALLBACK_TYPE | None = None

    @callback
    def send(_now: Any = None) -> None:
        nonlocal last_sent, timer
        timer = None
        entry = hass.config_entries.async_get_entry(entry_id)
        # The new engine starts before the entry counts as loaded.
        engine = getattr(entry, "runtime_data", None)
        if not isinstance(engine, BrightRoomsEngine) or not engine.running:
            return
        last_sent = time.monotonic()
        connection.send_message(
            websocket_api.event_message(msg["id"], engine.snapshot())
        )

    @callback
    def on_update() -> None:
        nonlocal timer
        if timer is not None:
            return
        wait = THROTTLE - (time.monotonic() - last_sent)
        if wait <= 0:
            send()
        else:
            timer = async_call_later(hass, wait, send)

    unsub = async_dispatcher_connect(hass, update_signal(entry_id), on_update)

    @callback
    def cancel() -> None:
        unsub()
        if timer is not None:
            timer()

    connection.subscriptions[msg["id"]] = cancel
    connection.send_result(msg["id"])
    send()


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "bright_rooms/schema", vol.Optional("room_id"): str}
)
@websocket_api.async_response
@_handle
async def ws_schema(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The room form and the settings form for ha-form, with their values."""
    entry = _entry(hass)
    if "room_id" in msg:
        sub = _room(entry, msg["room_id"])
        values = {
            **room_config(dict(sub.data)),
            CONF_NAME: room_title(hass, dict(sub.data), sub.title),
        }
    else:
        values = {**ROOM_DEFAULTS, CONF_SCHEDULE: []}
    connection.send_result(
        msg["id"],
        {
            "schema": _serialize(room_schema()),
            "values": {k: v for k, v in values.items() if v is not None},
            "settings_schema": _serialize(settings_schema()),
            "settings": settings(entry),
        },
    )


# ------------------------------------------------------------------ write


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "bright_rooms/room/save",
        vol.Optional("room_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
@_handle
async def ws_room_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add or edit a room; field errors come back in the result.

    Settings left out of the data take their default value. Without
    `schedule` in the data the room's time bands stay as they are.
    """
    entry = _entry(hass)
    current = _room(entry, msg["room_id"]) if "room_id" in msg else None
    try:
        form = room_schema()({**ROOM_DEFAULTS, **_form_data(msg["data"], room_keys())})
    except vol.Invalid as err:
        connection.send_result(msg["id"], {"errors": _field_errors(err)})
        return
    errors = validate_room(hass, entry, form, current.subentry_id if current else None)
    if CONF_SCHEDULE in msg["data"]:
        bands, band_errors = validate_schedule(msg["data"][CONF_SCHEDULE])
        errors.update(band_errors)
    else:
        bands = list(current.data.get(CONF_SCHEDULE) or []) if current else []
    if errors:
        connection.send_result(msg["id"], {"errors": errors})
        return
    data = {**normalize_room(form), CONF_SCHEDULE: bands}
    title = room_title(hass, data)
    if current is None:
        sub = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_ROOM,
            title=title,
            unique_id=None,
        )
        hass.config_entries.async_add_subentry(entry, sub)
        room_id = sub.subentry_id
    else:
        hass.config_entries.async_update_subentry(
            entry, current, data=data, title=title, unique_id=None
        )
        room_id = current.subentry_id
    connection.send_result(msg["id"], {"room_id": room_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "bright_rooms/room/delete", vol.Required("room_id"): str}
)
@websocket_api.async_response
@_handle
async def ws_room_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a room (its entities and device go with it; lights are left as they are)."""
    entry = _entry(hass)
    sub = _room(entry, msg["room_id"])
    hass.config_entries.async_remove_subentry(entry, sub.subentry_id)
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "bright_rooms/room/set_enabled",
        vol.Required("room_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
@_handle
async def ws_room_set_enabled(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The room's Automatic switch."""
    engine = _engine(hass)
    if msg["room_id"] not in engine.rooms:
        raise _Error(ERR_NOT_FOUND, "Unknown room")
    engine.set_room_enabled(msg["room_id"], msg["enabled"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "bright_rooms/contribution/set",
        vol.Required("room_id"): str,
        vol.Required("entity_id"): str,
        vol.Required("value"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0, max=100000))
        ),
    }
)
@websocket_api.async_response
@_handle
async def ws_contribution_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set a light's contribution by hand; null forgets it (learned again)."""
    engine = _engine(hass)
    room = engine.rooms.get(msg["room_id"])
    if room is None:
        raise _Error(ERR_NOT_FOUND, "Unknown room")
    if msg["entity_id"] not in room.cfg.lights:
        raise _Error(ERR_NOT_FOUND, "The light is not one of the room's lights")
    engine.set_contribution(msg["room_id"], msg["entity_id"], msg["value"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "bright_rooms/settings/save", vol.Required("data"): dict}
)
@websocket_api.async_response
@_handle
async def ws_settings_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save the global settings (the entry reloads)."""
    entry = _entry(hass)
    schema = settings_schema()
    try:
        # Settings left out keep their current value.
        data = schema(
            {
                **settings(entry),
                **_form_data(msg["data"], [str(k) for k in schema.schema]),
            }
        )
    except vol.Invalid as err:
        connection.send_result(msg["id"], {"errors": _field_errors(err)})
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, **normalize_settings(data)}
    )
    connection.send_result(msg["id"], {})
