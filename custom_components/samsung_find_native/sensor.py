from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.components.zone import async_active_zone
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BATTERY_LEVELS,
    DOMAIN,
    HINT_MAX_ACCURACY,
    HINT_MAX_AGE_MINUTES,
    HINT_KEY,
)
from .coordinator import SamsungFindCoordinator
from .entity import SamsungFindEntity, item_last_seen, to_datetime


def _loc(item: dict[str, Any], key: str) -> Any:
    return (item.get('location') or {}).get(key)


def _dev(item: dict[str, Any], key: str) -> Any:
    return (item.get('device') or {}).get(key)


def _battery_level(item: dict[str, Any]) -> str | None:
    value = _loc(item, 'battery')
    return value if value in BATTERY_LEVELS else None


@dataclass(frozen=True, kw_only=True)
class SamsungFindSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


DESCRIPTIONS = (
    SamsungFindSensorDescription(
        key='battery_percent',
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda item: item.get('battery_percent'),
    ),
    SamsungFindSensorDescription(
        key='battery',
        translation_key='battery_level',
        device_class=SensorDeviceClass.ENUM,
        options=list(BATTERY_LEVELS),
        value_fn=_battery_level,
    ),
    SamsungFindSensorDescription(
        key='last_seen',
        translation_key='last_seen',
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=item_last_seen,
    ),
    SamsungFindSensorDescription(
        key='accuracy',
        translation_key='accuracy',
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda item: _loc(item, 'accuracy'),
    ),
    SamsungFindSensorDescription(
        key='signal_strength',
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda item: _loc(item, 'rssi'),
    ),
    SamsungFindSensorDescription(
        key='speed',
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda item: _loc(item, 'speed'),
    ),
    SamsungFindSensorDescription(
        key='battery_updated',
        translation_key='battery_updated',
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda item: to_datetime(_dev(item, 'battery_updated')),
    ),
    SamsungFindSensorDescription(
        key='connection_state',
        translation_key='connection_state',
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda item: _loc(item, 'd2d_status'),
    ),
    SamsungFindSensorDescription(
        key='location_method',
        translation_key='location_method',
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda item: _loc(item, 'method'),
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
            if (device_id, HINT_KEY) not in known:
                known.add((device_id, HINT_KEY))
                entities.append(SamsungFindLocationHint(coordinator, device_id))
            for description in DESCRIPTIONS:
                key = (device_id, description.key)
                if key in known:
                    continue
                known.add(key)
                entities.append(
                    SamsungFindSensor(coordinator, device_id, description)
                )
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class SamsungFindSensor(SamsungFindEntity, SensorEntity):
    entity_description: SamsungFindSensorDescription

    def __init__(
        self,
        coordinator: SamsungFindCoordinator,
        device_id: str,
        description: SamsungFindSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f'{device_id}_{description.key}'

    @property
    def native_value(self) -> Any:
        item = self._item
        if not item:
            return None
        return self.entity_description.value_fn(item)

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != 'battery_percent':
            return None
        item = self._item or {}
        return {
            'estimated': item.get('battery_estimated'),
            'battery_level': _loc(item, 'battery'),
        }


class SamsungFindLocationHint(SamsungFindEntity, SensorEntity):
    """Supplementary position hint of the tag.

    Strict by design: a fix older than HINT_MAX_AGE_MINUTES or less accurate than
    HINT_MAX_ACCURACY metres is reported as "unconfirmed". It is only a hint and
    is never meant to confirm presence on its own.
    """

    _attr_translation_key = 'location_hint'

    def __init__(self, coordinator: SamsungFindCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f'{device_id}_{HINT_KEY}'

    def _fix(self) -> tuple[float, float, float, float] | None:
        """Return (lat, lon, accuracy, age in minutes) of a usable fix."""
        location = self._location
        if not location or not location.get('has_location'):
            return None
        try:
            lat = float(location['latitude'])
            lon = float(location['longitude'])
            accuracy = float(location.get('accuracy'))
        except (KeyError, TypeError, ValueError):
            return None
        seen = to_datetime(location.get('last_update_time'))
        if seen is None:
            return None
        age = (dt_util.utcnow() - seen).total_seconds() / 60
        return lat, lon, accuracy, age

    @property
    def native_value(self) -> str:
        fix = self._fix()
        if fix is None:
            return 'unconfirmed'
        lat, lon, accuracy, age = fix
        if age < 0 or age > HINT_MAX_AGE_MINUTES or accuracy > HINT_MAX_ACCURACY:
            return 'unconfirmed'
        zone = async_active_zone(self.hass, lat, lon, accuracy)
        if zone is None:
            return 'not_home'
        if zone.entity_id == 'zone.home':
            return 'home'
        return zone.name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fix = self._fix()
        return {
            'age_minutes': round(fix[3], 1) if fix else None,
            'accuracy': fix[2] if fix else None,
            'max_age_minutes': HINT_MAX_AGE_MINUTES,
            'max_accuracy': HINT_MAX_ACCURACY,
        }
