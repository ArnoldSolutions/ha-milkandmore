"""Config flow for Milk & More."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .api import MilkAndMoreAuthError, MilkAndMoreClient, MilkAndMoreError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class MilkAndMoreConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Milk & More website login and check it works."""

    VERSION = 1

    async def _test_login(self, email: str, password: str) -> str | None:
        """Return an error key, or None if the login worked."""
        # A short-lived session of our own, closed when the check is done
        # (HA's shared-helper sessions must not be closed by integrations).
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
            try:
                await MilkAndMoreClient(session, email, password).login()
            except MilkAndMoreAuthError:
                return "invalid_auth"
            except MilkAndMoreError:
                _LOGGER.exception("Error contacting Milk & More")
                return "cannot_connect"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            error = await self._test_login(email, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title=f"Milk & More ({email})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            error = await self._test_login(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )
