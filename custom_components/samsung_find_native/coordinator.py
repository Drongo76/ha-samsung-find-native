from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SamsungFindApi, SamsungFindApiError
from .auth import SamsungAuthError, SamsungAuthTemporaryError
from .const import (
    BATTERY_PERCENT_ESTIMATE,
    CONF_COUNTRY,
    CONF_LANGUAGE,
    CONF_OFFLINE_AFTER,
    CONF_PIN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_COUNTRY,
    DEFAULT_LANGUAGE,
    DEFAULT_OFFLINE_AFTER,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def timezone_offset() -> str:
    now = dt_util.now()
    offset = now.utcoffset()
    if offset is None:
        return 'UTC+00:00'
    total_minutes = int(offset.total_seconds() // 60)
    sign = '+' if total_minutes >= 0 else '-'
    total_minutes = abs(total_minutes)
    return f'UTC{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}'


class SamsungFindCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = int(
            entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.entry = entry
        self.offline_after = timedelta(
            minutes=int(entry.options.get(CONF_OFFLINE_AFTER, DEFAULT_OFFLINE_AFTER))
        )

        def save_auth_data(data: dict[str, Any]) -> None:
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    **data,
                },
            )

        self.api = SamsungFindApi(
            async_get_clientsession(hass),
            dict(entry.data),
            save_auth_data,
            country=str(entry.data.get(CONF_COUNTRY, DEFAULT_COUNTRY)),
            language=str(entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)),
            timezone_offset=timezone_offset(),
            pin=str(entry.options.get(CONF_PIN) or '') or None,
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            return await self._async_fetch()
        except SamsungAuthTemporaryError as exc:
            raise UpdateFailed(str(exc)) from exc
        except SamsungAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except SamsungFindApiError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def _async_fetch(self) -> dict[str, dict[str, Any]]:
        devices = await self.api.async_get_devices()

        async def load(device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            device_id = str(device['id'])
            base_location = {
                'latitude': None,
                'longitude': None,
                'has_location': False,
                'encrypted': bool(device.get('e2e_enabled')),
                'pin_required': False,
                'battery': device.get('battery'),
                'last_update_time': device.get('last_update_time'),
                'nearby': device.get('nearby'),
                'on_demand': device.get('on_demand'),
                'd2d_status': device.get('d2d_status'),
                'connected_user_id': device.get('connected_user_id'),
                'connected_device_id': device.get('connected_device_id'),
            }
            try:
                live = await self.api.async_get_location(device_id)
                location = {
                    **base_location,
                    **{
                        key: value
                        for key, value in live.items()
                        if value is not None
                    },
                }
                error = None
            except SamsungFindApiError as exc:
                location = base_location
                error = str(exc)

            battery = await self.api.async_get_battery_percent(device_id)
            percent = battery.get('percent')
            estimated = percent is None
            if estimated:
                percent = BATTERY_PERCENT_ESTIMATE.get(str(location.get('battery') or ''))

            return device_id, {
                'device': device,
                'location': location,
                'location_error': error,
                'battery_percent': percent,
                'battery_estimated': estimated,
                'battery_raw': battery.get('raw'),
            }

        loaded = await asyncio.gather(*(load(device) for device in devices))
        return dict(loaded)
