"""Sensors for Milk & More."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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
            NextDeliverySensor(coordinator),
            NextDeliveryItemsSensor(coordinator),
            NextDeliveryTotalSensor(coordinator),
            OrderCutoffSensor(coordinator),
            SkippedDeliveriesSensor(coordinator),
        ]
    )


class NextDeliverySensor(MilkAndMoreEntity, SensorEntity):
    """Date of the next delivery that has something on it."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "next_delivery")

    @property
    def native_value(self) -> date | None:
        nd = self.coordinator.data.next_delivery
        return nd.date if nd else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nd = self.coordinator.data.next_delivery
        if nd is None:
            return {}
        return {
            "items": [i.as_dict() for i in nd.items],
            "item_count": sum(i.quantity for i in nd.items),
            "total": nd.total,
            "editable": nd.editable,
            "summary": nd.summary(),
        }


class NextDeliveryItemsSensor(MilkAndMoreEntity, SensorEntity):
    """Plain-text list of what's coming next (handy for dashboards and Alexa)."""

    _attr_icon = "mdi:bottle-wine-outline"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "next_delivery_items")

    @property
    def native_value(self) -> str | None:
        nd = self.coordinator.data.next_delivery
        if nd is None:
            return "Nothing booked"
        text = nd.summary()
        return text if len(text) <= 255 else text[:252] + "..."

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nd = self.coordinator.data.next_delivery
        return {"items": [i.as_dict() for i in nd.items]} if nd else {}


class NextDeliveryTotalSensor(MilkAndMoreEntity, SensorEntity):
    """Cost of the next delivery."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "next_delivery_total")

    @property
    def native_value(self) -> float | None:
        nd = self.coordinator.data.next_delivery
        return nd.total if nd else None


class OrderCutoffSensor(MilkAndMoreEntity, SensorEntity):
    """When the next changeable delivery day locks (21:00 the night before)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "order_cutoff")

    @property
    def native_value(self) -> datetime | None:
        day = self.coordinator.data.next_editable_day
        return cutoff_for(day.date) if day else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        day = self.coordinator.data.next_editable_day
        if day is None:
            return {}
        return {
            "delivery_date": day.date.isoformat(),
            "has_items": day.has_items,
            "summary": day.summary(),
        }


class SkippedDeliveriesSensor(MilkAndMoreEntity, SensorEntity):
    """How many upcoming delivery days are skipped on the website."""

    _attr_icon = "mdi:truck-remove-outline"

    def __init__(self, coordinator: MilkAndMoreCoordinator) -> None:
        super().__init__(coordinator, "skipped_deliveries")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.skipped)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"dates": self.coordinator.data.skipped}
