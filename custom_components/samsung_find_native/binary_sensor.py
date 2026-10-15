from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SamsungFindCoordinator
from .entity import SamsungFindEntity, item_last_seen


def _nearby(coordinator: SamsungFindCoordinator, item: dict[str, Any]) -> bool | None:
    value = (item.get('location') or {}).get('nearby')
    return bool(value) if value is not None else None


def _online(coordinator: SamsungFindCoordinator, item: dict[str, Any]) -> bool | None:
    seen = item_last_seen(item)
    if seen is None:
        return None
    return dt_util.utcnow() - seen <= coordinator.offline_after


@dataclass(frozen=True, kw_only=True)
class SamsungFindBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[SamsungFindCoordinator, dict[str, Any]], bool | None]


DESCRIPTIONS = (
    SamsungFindBinarySensorDescription(
        key='nearby',
        translation_key='nearby',
        value_fn=_nearby,
    ),
    SamsungFindBinarySensorDescription(
        key='online',
        translation_key='online',
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_online,
    ),
    SamsungFindBinarySensorDescription(
        key='remote_ring',
        translation_key='remote_ring',
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator, item: bool(
            (item.get('device') or {}).get('remote_ring_enabled')
        ),
    ),
    SamsungFindBinarySensorDescription(
        key='e2e_encryption',
        translation_key='e2e_encryption',
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator, item: bool(
            (item.get('device') or {}).get('e2e_enabled')
        ),
    ),
    SamsungFindBinarySensorDescription(
        key='pin_required',
        translation_key='pin_required',
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator, item: bool(
            (item.get('location') or {}).get('pin_required')
        ),
    ),
    SamsungFindBinarySensorDescription(
        key='location_error',
        translation_key='location_error',
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator, item: item.get('location_error') is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SamsungFindCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    def add_new() -> None:
        data = coordinator.data or {}
        entities = []
        for device_id in data:
            for description in DESCRIPTIONS:
                key = (device_id, description.key)
                if key in known:
                    continue
                known.add(key)
                entities.append(
                    SamsungFindBinarySensor(coordinator, device_id, description)
                )
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class SamsungFindBinarySensor(SamsungFindEntity, BinarySensorEntity):
    entity_description: SamsungFindBinarySensorDescription

    def __init__(
        self,
        coordinator: SamsungFindCoordinator,
        device_id: str,
        description: SamsungFindBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f'{device_id}_{description.key}'

    @property
    def is_on(self) -> bool | None:
        item = self._item
        if not item:
            return None
        return self.entity_description.value_fn(self.coordinator, item)

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != 'location_error':
            return None
        return {'error': (self._item or {}).get('location_error')}
