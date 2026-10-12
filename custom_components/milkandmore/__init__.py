"""The Milk & More integration (unofficial)."""

from __future__ import annotations

from datetime import date

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import MilkAndMoreClient, MilkAndMoreError
from .const import DOMAIN
from .coordinator import MilkAndMoreConfigEntry, MilkAndMoreCoordinator, cutoff_for

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SKIP = "skip_deliveries"
SERVICE_UNSKIP = "unskip_deliveries"
SERVICE_SCHEMA = vol.Schema({vol.Required("dates"): vol.All(cv.ensure_list, [cv.date])})


def _coordinator(hass: HomeAssistant) -> MilkAndMoreCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise HomeAssistantError("Milk & More is not set up or not signed in")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the skip / restore actions."""

    async def _handle(call: ServiceCall, skip: bool) -> ServiceResponse:
        coordinator = _coordinator(hass)
        now = dt_util.now()
        dates: list[date] = sorted(set(call.data["dates"]))
        # The website only accepts changes until 21:00 the night before.
        allowed = [d.isoformat() for d in dates if cutoff_for(d) > now]
        too_late = [d.isoformat() for d in dates if cutoff_for(d) <= now]
        result: dict = {"changed": [], "already": [], "failed": [], "too_late": too_late}
        if allowed:
            try:
                if skip:
                    res = await coordinator.client.async_skip(allowed)
                else:
                    res = await coordinator.client.async_unskip(allowed)
            except MilkAndMoreError as err:
                raise HomeAssistantError(f"Milk & More: {err}") from err
            result.update(res)
            await coordinator.async_request_refresh()
        if result["failed"]:
            raise HomeAssistantError(
                "Milk & More did not accept the change for " + ", ".join(result["failed"])
            )
        return result

    async def _skip(call: ServiceCall) -> ServiceResponse:
        return await _handle(call, skip=True)

    async def _unskip(call: ServiceCall) -> ServiceResponse:
        return await _handle(call, skip=False)

    hass.services.async_register(
        DOMAIN, SERVICE_SKIP, _skip, schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNSKIP, _unskip, schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MilkAndMoreConfigEntry) -> bool:
    """Set up Milk & More from a config entry."""
    # Own session with its own cookie jar, so the website login cookie
    # never mixes with HA's shared session.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    client = MilkAndMoreClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])

    coordinator = MilkAndMoreCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MilkAndMoreConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
