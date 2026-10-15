from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SamsungFindApiError
from .const import ATTR_ACTION, DOMAIN, SERVICE_RING
from .coordinator import SamsungFindCoordinator
from .entity import SamsungFindEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SamsungFindCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    def add_new() -> None:
        data = coordinator.data or {}
        new_ids = [device_id for device_id in data if device_id not in known]
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            [SamsungFindTracker(coordinator, device_id) for device_id in new_ids]
        )

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_RING,
        {vol.Required(ATTR_ACTION): vol.In(['start', 'stop'])},
        'async_ring',
    )


class SamsungFindTracker(SamsungFindEntity, TrackerEntity):
    _attr_name = None
    _attr_translation_key = 'tag'

    def __init__(self, coordinator: SamsungFindCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f'{device_id}_tracker'

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        location = self._location
        return location.get('latitude') if location else None

    @property
    def longitude(self) -> float | None:
        location = self._location
        return location.get('longitude') if location else None

    @property
    def location_accuracy(self) -> int:
        location = self._location
        if not location or location.get('accuracy') is None:
            return 0
        return max(0, round(float(location['accuracy'])))

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._location is not None
            and bool(self._location.get('has_location'))
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        location = self._location or {}
        item = self._item or {}
        return {
            'last_update_time': location.get('last_update_time'),
            'method': location.get('method'),
            'rssi': location.get('rssi'),
            'speed': location.get('speed'),
            'nearby': location.get('nearby'),
            'on_demand': location.get('on_demand'),
            'valid': location.get('valid'),
            'encrypted': location.get('encrypted'),
            'pin_required': location.get('pin_required'),
            'find_node': location.get('find_node'),
            'battery_level': item.get('battery_percent'),
            'battery_estimated': item.get('battery_estimated'),
            'location_error': item.get('location_error'),
        }

    async def async_ring(self, action: str) -> None:
        try:
            await self.coordinator.api.async_ring(self.device_id, action == 'start')
        except SamsungFindApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='ring_failed',
                translation_placeholders={'error': str(exc)},
            ) from exc
        await self.coordinator.async_request_refresh()
