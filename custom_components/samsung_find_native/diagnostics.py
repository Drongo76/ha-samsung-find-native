from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SamsungFindCoordinator

TO_REDACT = {
    'access_token',
    'refresh_token',
    'userauth_token',
    'user_id',
    'login_id',
    'physical_address',
    'auth_server_url',
    'find_token',
    'iot_token',
    'latitude',
    'longitude',
    'pin',
    'id',
    'name',
    'unique_id',
    'connected_user_id',
    'connected_device_id',
    'find_node',
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: SamsungFindCoordinator = hass.data[DOMAIN][entry.entry_id]
    devices = {
        f'device_{index}': async_redact_data(item, TO_REDACT)
        for index, item in enumerate((coordinator.data or {}).values(), start=1)
    }
    return {
        'entry': async_redact_data(entry.as_dict(), TO_REDACT),
        'last_update_success': coordinator.last_update_success,
        'update_interval_seconds': (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
        'devices': devices,
    }
