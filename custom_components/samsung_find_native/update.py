from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
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
            [SamsungFindFirmwareUpdate(coordinator, device_id) for device_id in new_ids]
        )

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class SamsungFindFirmwareUpdate(SamsungFindEntity, UpdateEntity):
    _attr_translation_key = 'firmware'
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(self, coordinator: SamsungFindCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f'{device_id}_firmware'

    @property
    def installed_version(self) -> str | None:
        return self._device.get('firmware')

    @property
    def latest_version(self) -> str | None:
        return self._device.get('latest_firmware') or self.installed_version

    @property
    def available(self) -> bool:
        return super().available and self.installed_version is not None
