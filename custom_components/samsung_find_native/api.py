from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Callable

from aiohttp import ClientSession

from .auth import SamsungAuthError, SamsungAuthManager
from .const import FME_PLUGIN_ID, SMARTTHINGS_APP_VERSION, SMARTTHINGS_USER_AGENT
from .crypto import decrypt_coordinates


class SamsungFindApiError(Exception):
    pass


class SamsungFindApi:
    def __init__(
        self,
        session: ClientSession,
        auth_data: dict[str, Any],
        save_auth_data: Callable[[dict[str, Any]], None],
        *,
        country: str,
        language: str,
        timezone_offset: str,
        pin: str | None,
    ) -> None:
        self._session = session
        self.auth = SamsungAuthManager(session, auth_data, save_auth_data)
        self.country = country.upper()
        self.language = language
        self.timezone_offset = timezone_offset
        self.pin = pin or None
        self._installed_app_id: str | None = None
        self._correlation = str(uuid.uuid4())

    async def _headers(self) -> dict[str, str]:
        token = await self.auth.async_access_token("iot")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.smartthings+json;v=1",
            "Accept-Language": f"{self.language}-{self.country}",
            "User-Agent": SMARTTHINGS_USER_AGENT,
            "X-St-Client-Appversion": SMARTTHINGS_APP_VERSION,
            "X-St-Client-Devicemodel": "SM-S928B",
            "X-St-Client-Os": "Android 16",
            "X-St-Correlation": self._correlation,
        }

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = await self._headers()
        if extra_headers:
            headers.update(extra_headers)
        async with self._session.request(
            method,
            url,
            headers=headers,
            json=body,
            allow_redirects=False,
        ) as response:
            if response.status == 401:
                await self.auth.async_access_token("iot", force_refresh=True)
                headers = await self._headers()
                if extra_headers:
                    headers.update(extra_headers)
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=body,
                    allow_redirects=False,
                ) as retry:
                    if retry.status == 401:
                        raise SamsungAuthError('SmartThings rejected the refreshed token')
                    return await self._decode_json(retry, "SmartThings")
            return await self._decode_json(response, "SmartThings")

    @staticmethod
    async def _decode_json(response, step: str) -> dict[str, Any]:
        if response.status < 200 or response.status >= 300:
            text = await response.text()
            raise SamsungFindApiError(
                f"{step} HTTP {response.status}: {text[:180]}"
            )
        try:
            data = await response.json(content_type=None)
        except Exception as exc:
            raise SamsungFindApiError(f"{step} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise SamsungFindApiError(f"{step} returned unexpected data")
        return data

    async def _raw_devices(self) -> list[dict[str, Any]]:
        data = await self._request_json("GET", "https://api.smartthings.com/devices")
        return list(data.get("items") or [])

    @staticmethod
    def _is_tracker(item: dict[str, Any]) -> bool:
        for component in item.get("components") or []:
            for category in component.get("categories") or []:
                if str(category.get("name") or "").lower() == "bluetoothtracker":
                    return True
        return False

    async def async_installed_app_id(self) -> str:
        if self._installed_app_id:
            return self._installed_app_id

        data = await self._request_json(
            "GET", "https://api.smartthings.com/installedapps?allowed=true"
        )
        items = list(data.get("items") or [])
        user_id = self.auth.user_id
        selected = next(
            (
                item
                for item in items
                if ((item.get("ui") or {}).get("pluginId") == FME_PLUGIN_ID)
                and str(((item.get("owner") or {}).get("ownerId") or "")) == user_id
            ),
            None,
        )
        if selected is None:
            selected = next(
                (
                    item
                    for item in items
                    if ((item.get("ui") or {}).get("pluginId") == FME_PLUGIN_ID)
                ),
                None,
            )
        if not selected or not selected.get("installedAppId"):
            raise SamsungFindApiError("Samsung Find installed app was not returned")
        self._installed_app_id = str(selected["installedAppId"])
        return self._installed_app_id

    async def _execute(
        self,
        method: str,
        uri: str,
        *,
        extra_uri: str | None = None,
        extra_parameters: dict[str, str] | None = None,
        body: Any = None,
    ) -> Any:
        installed_app_id = await self.async_installed_app_id()
        token = await self.auth.async_access_token("iot")

        client = {
            "displayMode": "LIGHT",
            "language": f"{self.language}-{self.country}",
            "mobileDeviceId": self.auth.device_id,
            "os": "Android",
            "samsungAccountId": self.auth.user_id,
            "supportedTemplates": [
                "BASIC_V1",
                "BASIC_V2",
                "BASIC_V3",
                "BASIC_V4",
                "BASIC_V5",
                "BASIC_V6",
                "BASIC_V7",
            ],
            "timeZoneOffset": self.timezone_offset,
            "version": SMARTTHINGS_APP_VERSION,
        }
        parameters: dict[str, Any] = {
            "requester": self.auth.user_id,
            "clientType": "aPlugin",
            "extraUri": extra_uri,
            "method": method.upper(),
            "encodedHeaders": "",
            "requesterToken": token,
            "encodedBody": (
                base64.b64encode(
                    json.dumps(body, separators=(",", ":")).encode()
                ).decode()
                if body is not None
                else ""
            ),
            "clientVersion": "1",
            "uri": uri,
        }
        if extra_parameters:
            parameters.update(extra_parameters)

        wrapper = await self._request_json(
            "POST",
            f"https://api.smartthings.com/installedapps/{installed_app_id}/execute",
            body={"client": client, "parameters": parameters},
        )
        status_code = int(wrapper.get("statusCode", 0))
        if status_code != 200:
            raise SamsungFindApiError(
                f"Samsung Find execute failed: {status_code} "
                f"{wrapper.get('errorCode') or ''}"
            )
        return wrapper.get("message")

    async def async_get_devices(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in await self._raw_devices():
            if not self._is_tracker(item):
                continue
            device_id = item.get("deviceId")
            if not device_id:
                continue
            metadata = ((item.get("bleD2D") or {}).get("metadata") or {})
            connection = metadata.get("lastKnownConnection") or {}
            battery = metadata.get("battery") or {}
            e2e = metadata.get("e2eEncryption") or {}
            remote_ring = metadata.get("remoteRing") or {}
            firmware = metadata.get('firmware') or {}
            result.append(
                {
                    "id": str(device_id),
                    "name": str(item.get("label") or item.get("name") or device_id),
                    "model": ((metadata.get("vendor") or {}).get("modelName")),
                    "battery": str(battery.get("level") or "UNKNOWN").lower(),
                    "battery_updated": _to_int(battery.get("updated")),
                    "nearby": connection.get("nearby"),
                    "on_demand": connection.get("onDemand"),
                    "d2d_status": connection.get("d2dStatus"),
                    "last_update_time": _to_int(connection.get("updated")),
                    "connected_user_id": ((connection.get("connectedUser") or {}).get("id")),
                    "connected_device_id": ((connection.get("connectedDevice") or {}).get("id")),
                    "e2e_enabled": bool(e2e.get("enabled", False)),
                    "remote_ring_enabled": bool(remote_ring.get("enabled", False)),
                    'firmware': firmware.get('version'),
                    'latest_firmware': (firmware.get('latestFirmware') or {}).get('version'),
                    'searching_status': metadata.get('searchingStatus'),
                }
            )
        return result

    async def async_probe(self) -> int:
        devices = await self.async_get_devices()
        if not devices:
            raise SamsungFindApiError("No BluetoothTracker devices found in SmartThings")
        await self.async_installed_app_id()
        return len(devices)

    async def async_get_location(self, device_id: str) -> dict[str, Any]:
        message = await self._execute(
            "GET",
            "/trackers/geolocation",
            extra_parameters={"stDids": device_id},
        )
        if not isinstance(message, dict):
            raise SamsungFindApiError("Samsung Find location response is invalid")

        items = message.get("items") or []
        item = next(
            (value for value in items if str(value.get("deviceId")) == device_id),
            None,
        )
        if item is None:
            raise SamsungFindApiError("Samsung Find returned no location item")
        result_code = int(item.get("resultCode", 0))
        if result_code == 403:
            raise SamsungFindApiError("Location access is not allowed for this tag")
        if result_code not in (0, 200):
            raise SamsungFindApiError(
                f"Samsung Find location result code {result_code}"
            )

        locations = item.get("geolocations") or item.get("geoLocations") or []
        if not locations:
            return {
                "latitude": None,
                "longitude": None,
                "has_location": False,
                "encrypted": False,
                "pin_required": False,
            }

        location = locations[0]
        key_pairs = message.get("keyPairs") or []
        key_pair = key_pairs[0] if key_pairs else None
        try:
            latitude, longitude, encrypted, pin_required = decrypt_coordinates(
                str(location.get("latitude") or ""),
                str(location.get("longitude") or ""),
                key_pair,
                self.pin,
            )
        except Exception as exc:
            raise SamsungFindApiError(
                "Samsung Find E2E location decryption failed"
            ) from exc

        return {
            "latitude": latitude,
            "longitude": longitude,
            "has_location": latitude is not None and longitude is not None,
            "encrypted": encrypted,
            "pin_required": pin_required,
            "accuracy": _to_float(location.get("accuracy")),
            "speed": _to_float(location.get("speed")),
            "rssi": _to_int(location.get("rssi")),
            "battery": str(location.get("battery") or "UNKNOWN").lower(),
            "last_update_time": _to_int(location.get("lastUpdateTime")),
            "valid": bool(location.get("valid", False)),
            "nearby": location.get("nearby"),
            "on_demand": location.get("onDemand"),
            "method": location.get("method"),
            "d2d_status": location.get("d2dStatus"),
            "find_node": (location.get("findNode") or {}).get("host"),
            "connected_user_id": (location.get("connectedUser") or {}).get("id"),
            "connected_device_id": (location.get("connectedDevice") or {}).get("id"),
        }

    async def async_get_battery_percent(self, device_id: str) -> dict[str, Any]:
        try:
            status = await self._request_json(
                'GET', f'https://api.smartthings.com/devices/{device_id}/status'
            )
        except SamsungFindApiError:
            return {'percent': None, 'raw': None}
        main = (status.get('components') or {}).get('main') or {}
        raw = ((main.get('battery') or {}).get('battery') or {}).get('value')
        percent = _to_int(raw)
        if percent is None or not 0 <= percent <= 100:
            percent = None
        return {'percent': percent, 'raw': raw}

    async def async_ring(self, device_id: str, ringing: bool) -> None:
        await self._execute(
            "PUT",
            "/trackerapi",
            extra_uri=f"/trackers/{device_id}/ring",
            body={"command": "start" if ringing else "stop"},
        )

    async def async_set_searching(self, device_id: str, searching: bool) -> None:
        await self._execute(
            "PUT",
            "/trackerapi",
            extra_uri=f"/trackers/{device_id}/searchingstatus",
            body={"searchingStatus": "SEARCHING" if searching else "STOP"},
        )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
