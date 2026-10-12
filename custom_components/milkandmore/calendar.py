"""Calendar of Milk & More deliveries."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import DeliveryDay
from .coordinator import MilkAndMoreConfigEntry, MilkAndMoreCoordinator
from .entity import MilkAndMoreEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MilkAndMoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([DeliveriesCalendar(entry.runtime_data)])


def _event(day: DeliveryDay) -> CalendarEvent:
    lines = [f"{i.quantity}× {i.name}" for i in day.items]
    if day.total is not None:
        lines.append(f"Total: £{day.total:.2f}")
    return CalendarEvent(
        start=day.date,
        end=day.date + timedelta(days=1),
        summary="Milk & More delivery",
        description="\n".join(lines),
    )


class DeliveriesCalendar(MilkAndMoreEntity, CalendarEntity):
    """All-day event on each day something is being delivered."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "deliveries")

    def _delivery_days(self) -> list[DeliveryDay]:
        return [d for d in self.coordinator.data.days if d.has_items]

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        upcoming = [d for d in self._delivery_days() if d.date >= today]
        return _event(upcoming[0]) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start, end = start_date.date(), end_date.date()
        return [_event(d) for d in self._delivery_days() if start <= d.date <= end]
