"""Data coordinator for Milk & More."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DeliveryDay, MilkAndMoreAuthError, MilkAndMoreClient, MilkAndMoreError
from .const import CUTOFF_HOUR, DOMAIN, UK_TZ, UPDATE_INTERVAL, WEEKS_AHEAD

_LOGGER = logging.getLogger(__name__)


@dataclass
class MilkAndMoreData:
    """Everything the entities need, worked out once per refresh."""

    days: list[DeliveryDay]
    next_delivery: DeliveryDay | None
    next_editable_day: DeliveryDay | None

    def day_for(self, when: date) -> DeliveryDay | None:
        return next((d for d in self.days if d.date == when), None)


def cutoff_for(day: date) -> datetime:
    """21:00 UK time on the day before delivery."""
    tz = dt_util.get_time_zone(UK_TZ)
    return datetime.combine(day - timedelta(days=1), time(CUTOFF_HOUR), tzinfo=tz)


type MilkAndMoreConfigEntry = ConfigEntry["MilkAndMoreCoordinator"]


class MilkAndMoreCoordinator(DataUpdateCoordinator[MilkAndMoreData]):
    """Polls the website for this week and the next few."""

    config_entry: MilkAndMoreConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MilkAndMoreConfigEntry, client: MilkAndMoreClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> MilkAndMoreData:
        today = dt_util.now().date()
        monday = today - timedelta(days=today.weekday())
        days: list[DeliveryDay] = []
        try:
            for week in range(WEEKS_AHEAD + 1):
                days.extend(await self.client.async_get_week(monday + timedelta(weeks=week)))
        except MilkAndMoreAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MilkAndMoreError as err:
            raise UpdateFailed(str(err)) from err

        # De-duplicate by date (keep the last seen) and sort.
        by_date = {d.date: d for d in days}
        days = [by_date[k] for k in sorted(by_date)]

        upcoming = [d for d in days if d.date >= today and d.has_items and not d.is_complete]
        now = dt_util.now()
        editable = [d for d in days if d.date > today and d.editable and cutoff_for(d.date) > now]

        return MilkAndMoreData(
            days=days,
            next_delivery=upcoming[0] if upcoming else None,
            next_editable_day=editable[0] if editable else None,
        )
