"""Base entity for Milk & More."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN
from .coordinator import MilkAndMoreCoordinator


class MilkAndMoreEntity(CoordinatorEntity[MilkAndMoreCoordinator]):
    """Shared device info and naming."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MilkAndMoreCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Milk & More",
            manufacturer="Milk & More",
            model="Doorstep delivery",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{BASE_URL}/my-account/my-orders-new",
        )
