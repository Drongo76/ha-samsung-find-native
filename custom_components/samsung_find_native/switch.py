from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SamsungFindApiError
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
            [SamsungFindSearchSwitch(coordinator, device_id) for device_id in new_ids]
        )

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class SamsungFindSearchSwitch(SamsungFindEntity, SwitchEntity):
    _attr_translation_key = 'searching'
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SamsungFindCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f'{device_id}_searching'

    @property
    def is_on(self) -> bool | None:
        status = self._device.get('searching_status')
        if status is None:
            return None
        return str(status).lower() == 'searching'

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, searching: bool) -> None:
        try:
            await self.coordinator.api.async_set_searching(self.device_id, searching)
        except SamsungFindApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='searching_failed',
                translation_placeholders={'error': str(exc)},
            ) from exc
        await self.coordinator.async_request_refresh()
