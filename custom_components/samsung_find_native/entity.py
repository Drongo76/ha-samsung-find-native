from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL_NAMES
from .coordinator import SamsungFindCoordinator


def to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def item_last_seen(item: dict[str, Any] | None) -> datetime | None:
    if not item:
        return None
    location = item.get('location') or {}
    device = item.get('device') or {}
    seen = [
        value
        for value in (
            to_datetime(location.get('last_update_time')),
            to_datetime(device.get('last_update_time')),
        )
        if value is not None
    ]
    return max(seen) if seen else None


class SamsungFindEntity(CoordinatorEntity[SamsungFindCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SamsungFindCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f'{device_id}_{self.__class__.__name__.lower()}'

    @property
    def _item(self) -> dict[str, Any] | None:
        return self.coordinator.data.get(self.device_id) if self.coordinator.data else None

    @property
    def _device(self) -> dict[str, Any]:
        item = self._item or {}
        return item.get('device') or {'id': self.device_id, 'name': self.device_id}

    @property
    def _location(self) -> dict[str, Any] | None:
        item = self._item or {}
        return item.get('location')

    @property
    def device_info(self) -> DeviceInfo:
        raw_model = self._device.get('model')
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer='Samsung',
            model=MODEL_NAMES.get(str(raw_model), str(raw_model)) if raw_model else None,
            model_id=str(raw_model) if raw_model else None,
            name=str(self._device.get('name') or self.device_id),
            sw_version=self._device.get('firmware'),
        )
