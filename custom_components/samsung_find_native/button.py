from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SamsungFindApiError
from .const import DOMAIN
from .coordinator import SamsungFindCoordinator
from .entity import SamsungFindEntity


@dataclass(frozen=True, kw_only=True)
class SamsungFindButtonDescription(ButtonEntityDescription):
    action: str


DESCRIPTIONS = (
    SamsungFindButtonDescription(
        key='refresh',
        translation_key='refresh',
        action='refresh',
    ),
    SamsungFindButtonDescription(
        key='ring_start',
        translation_key='ring_start',
        action='ring_start',
    ),
    SamsungFindButtonDescription(
        key='ring_stop',
        translation_key='ring_stop',
        action='ring_stop',
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
                    SamsungFindButton(coordinator, device_id, description)
                )
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class SamsungFindButton(SamsungFindEntity, ButtonEntity):
    entity_description: SamsungFindButtonDescription

    def __init__(
        self,
        coordinator: SamsungFindCoordinator,
        device_id: str,
        description: SamsungFindButtonDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f'{device_id}_{description.key}'

    async def async_press(self) -> None:
        action = self.entity_description.action
        if action == 'refresh':
            await self.coordinator.async_request_refresh()
            return
        try:
            await self.coordinator.api.async_ring(self.device_id, action == 'ring_start')
        except SamsungFindApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='ring_failed',
                translation_placeholders={'error': str(exc)},
            ) from exc
        await self.coordinator.async_request_refresh()
