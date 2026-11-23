"""Config flow for Bright Rooms."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback

from .const import (
    CONF_AREA,
    DOMAIN,
    ROOM_DEFAULTS,
    SETTINGS_DEFAULTS,
    SUBENTRY_ROOM,
    TITLE,
)
from .schema import (
    normalize_room,
    normalize_settings,
    room_schema,
    room_title,
    settings,
    settings_schema,
    validate_room,
)


class BrightRoomsConfigFlow(ConfigFlow, domain=DOMAIN):
    """A single entry; rooms are its subentries."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then create the entry with the default settings."""
        if user_input is not None:
            return self.async_create_entry(
                title=TITLE, data={}, options=dict(SETTINGS_DEFAULTS)
            )
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BrightRoomsOptionsFlow:
        """Global settings."""
        return BrightRoomsOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Rooms are subentries."""
        return {SUBENTRY_ROOM: RoomSubentryFlow}


class BrightRoomsOptionsFlow(OptionsFlow):
    """Global settings: settling time and contribution learning."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One step."""
        if user_input is not None:
            return self.async_create_entry(data=normalize_settings(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                settings_schema(), settings(self.config_entry)
            ),
        )


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or edit a room."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a room."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_room(self._get_entry(), user_input, None)
            if not errors:
                return self.async_create_entry(
                    title=room_title(self.hass, user_input),
                    data=normalize_room(user_input),
                    unique_id=user_input[CONF_AREA],
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                room_schema(), user_input or ROOM_DEFAULTS
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a room."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_room(self._get_entry(), user_input, subentry.subentry_id)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=room_title(self.hass, user_input),
                    data=normalize_room(user_input),
                    unique_id=user_input[CONF_AREA],
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                room_schema(), user_input or {**ROOM_DEFAULTS, **subentry.data}
            ),
            errors=errors,
        )
