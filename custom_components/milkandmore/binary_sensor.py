"""Binary sensors for Milk & More."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MilkAndMoreConfigEntry, MilkAndMoreCoordinator, cutoff_for
from .entity import MilkAndMoreEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MilkAndMoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DeliveryTomorrowSensor(coordinator),
            NextDeliveryEditableSensor(coordinator),
        ]
    )


class DeliveryTomorrowSensor(MilkAndMoreEntity, BinarySensorEntity):
    """On when something is due tomorrow morning."""

    _attr_icon = "mdi:truck-delivery-outline"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "delivery_tomorrow")

    @property
    def is_on(self) -> bool:
        tomorrow = dt_util.now().date() + timedelta(days=1)
        day = self.coordinator.data.day_for(tomorrow)
        return bool(day and day.has_items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tomorrow = dt_util.now().date() + timedelta(days=1)
        day = self.coordinator.data.day_for(tomorrow)
        if day is None or not day.has_items:
            return {}
        return {"summary": day.summary(), "total": day.total}


class NextDeliveryEditableSensor(MilkAndMoreEntity, BinarySensorEntity):
    """On while the next delivery can still be changed on the website."""

    _attr_icon = "mdi:pencil-lock-outline"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "next_delivery_editable")

    @property
    def is_on(self) -> bool:
        nd = self.coordinator.data.next_delivery
        if nd is None or not nd.editable:
            return False
        return dt_util.now() < cutoff_for(nd.date)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nd = self.coordinator.data.next_delivery
        return {"cutoff": cutoff_for(nd.date).isoformat()} if nd else {}
