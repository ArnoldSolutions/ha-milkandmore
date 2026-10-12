"""The Milk & More integration (unofficial)."""

from __future__ import annotations

import aiohttp

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import MilkAndMoreClient
from .coordinator import MilkAndMoreConfigEntry, MilkAndMoreCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]


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
