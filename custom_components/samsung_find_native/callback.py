from __future__ import annotations

import hmac
import logging
import time
import urllib.parse
from typing import Any

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .auth import SamsungAuthBootstrap, SamsungAuthError
from .const import DOMAIN, REDIRECT_URI

DATA_AUTH_FLOWS = "_auth_flows"
DATA_CALLBACK_VIEW = "_callback_view_registered"

START_PATH = "/api/samsung_find_native/start"
PREPARE_PATH = "/api/samsung_find_native/prepare"
CALLBACK_PATH = "/api/samsung_find_native/callback"
BRIDGE_SCHEME = "samsungfindbridge"
AUTH_TTL = 900
_LOGGER = logging.getLogger(__name__)


def _domain_data(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(DOMAIN, {})


def _flow_store(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    return _domain_data(hass).setdefault(DATA_AUTH_FLOWS, {})


@callback
def async_register_auth_flow(
    hass: HomeAssistant,
    flow_id: str,
    *,
    nonce: str,
    created_at: float | None = None,
) -> None:
    store = _flow_store(hass)
    now = time.time()
    for old_flow_id, record in list(store.items()):
        if now - float(record.get("created_at", 0)) > AUTH_TTL:
            store.pop(old_flow_id, None)
    store[flow_id] = {
        "nonce": nonce,
        "created_at": created_at or now,
    }


@callback
def async_get_auth_flow(
    hass: HomeAssistant, flow_id: str
) -> dict[str, Any] | None:
    record = _flow_store(hass).get(flow_id)
    if record is None:
        return None
    age = time.time() - float(record.get("created_at", 0))
    if age < -60 or age > AUTH_TTL:
        _flow_store(hass).pop(flow_id, None)
        return None
    return record


@callback
def async_remove_auth_flow(hass: HomeAssistant, flow_id: str) -> None:
    _flow_store(hass).pop(flow_id, None)


@callback
def ensure_callback_views(hass: HomeAssistant) -> None:
    data = _domain_data(hass)
    if data.get(DATA_CALLBACK_VIEW):
        return
    hass.http.register_view(SamsungFindStartView)
    hass.http.register_view(SamsungFindPrepareView)
    hass.http.register_view(SamsungFindCallbackView)
    data[DATA_CALLBACK_VIEW] = True


def external_base_url(hass: HomeAssistant) -> str:
    return get_url(
        hass,
        require_ssl=True,
        allow_internal=False,
        allow_external=True,
        allow_cloud=False,
        prefer_external=True,
    ).rstrip("/")


def _valid_redirect_uri(value: str) -> bool:
    try:
        actual = urllib.parse.urlsplit(value)
        expected = urllib.parse.urlsplit(REDIRECT_URI)
    except (TypeError, ValueError):
        return False
    return (
        actual.scheme.lower(),
        actual.netloc.lower(),
        actual.path,
    ) == (
        expected.scheme.lower(),
        expected.netloc.lower(),
        expected.path,
    )


class SamsungFindStartView(HomeAssistantView):
    url = START_PATH
    name = "api:samsung_find_native:start"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass: HomeAssistant = request.app[KEY_HASS]
        flow_id = str(request.query.get("flow_id") or "")
        nonce = str(request.query.get("nonce") or "")
        record = async_get_auth_flow(hass, flow_id)
        if (
            record is None
            or not nonce
            or not hmac.compare_digest(str(record.get("nonce") or ""), nonce)
        ):
            raise web.HTTPGone(text="Samsung Find setup session expired")

        try:
            ha_url = external_base_url(hass)
        except NoURLAvailableError as exc:
            raise web.HTTPServiceUnavailable(
                text="Home Assistant external HTTPS URL is unavailable"
            ) from exc

        bridge_uri = (
            f"{BRIDGE_SCHEME}://start?"
            + urllib.parse.urlencode(
                {
                    "flow_id": flow_id,
                    "nonce": nonce,
                    "ha": ha_url,
                }
            )
        )
        raise web.HTTPFound(location=bridge_uri)


class SamsungFindPrepareView(HomeAssistantView):
    url = PREPARE_PATH
    name = "api:samsung_find_native:prepare"
    requires_auth = False

    async def post(self, request: web.Request) -> web.StreamResponse:
        hass: HomeAssistant = request.app[KEY_HASS]
        try:
            body = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Invalid request")

        flow_id = str(body.get("flow_id") or "")
        nonce = str(body.get("nonce") or "")
        record = async_get_auth_flow(hass, flow_id)
        if (
            record is None
            or not nonce
            or not hmac.compare_digest(str(record.get("nonce") or ""), nonce)
        ):
            raise web.HTTPGone(text="Samsung Find setup session expired")

        device_id = str(body.get("device_id") or "").strip()
        manufacturer = str(body.get("manufacturer") or "samsung").strip()
        model = str(body.get("model") or "SM-S928B").strip()
        os_version = str(body.get("os_version") or "36").strip()

        if not (8 <= len(device_id) <= 64):
            raise web.HTTPBadRequest(text="Invalid Android device id")
        if len(manufacturer) > 64 or len(model) > 96 or len(os_version) > 16:
            raise web.HTTPBadRequest(text="Invalid device information")

        auth = SamsungAuthBootstrap(async_get_clientsession(hass))
        try:
            login_url, pending = await auth.async_start(
                "DE",
                "de-DE",
                device_id=device_id,
                manufacturer=manufacturer,
                model=model,
                os_version=os_version,
            )
        except Exception as exc:
            raise web.HTTPBadGateway(text="Samsung sign-in could not be started") from exc

        record["pending"] = pending
        record["prepared_at"] = time.time()
        return web.json_response({"ok": True, "login_url": login_url})


class SamsungFindCallbackView(HomeAssistantView):
    url = CALLBACK_PATH
    name = "api:samsung_find_native:callback"
    requires_auth = False

    async def post(self, request: web.Request) -> web.StreamResponse:
        hass: HomeAssistant = request.app[KEY_HASS]
        try:
            body = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Invalid request")

        redirect_uri = str(body.get("redirect_uri") or "").strip()
        if len(redirect_uri) > 16384 or not _valid_redirect_uri(redirect_uri):
            raise web.HTTPBadRequest(text="Invalid Samsung callback")

        auth = SamsungAuthBootstrap(async_get_clientsession(hass))
        matched_flow_id: str | None = None
        store = _flow_store(hass)
        _LOGGER.debug('Samsung callback: %d stored flow(s), %d with pending', len(store), sum(1 for r in store.values() if isinstance(r.get('pending'), dict)))
        for flow_id, record in list(store.items()):
            pending = record.get('pending')
            if not isinstance(pending, dict):
                continue
            try:
                auth._decode_callback(redirect_uri, pending)
            except SamsungAuthError as exc:
                _LOGGER.warning('Samsung callback rejected for flow %s: %s', flow_id[:6], exc)
                continue
            matched_flow_id = flow_id
            break

        if matched_flow_id is None:
            raise web.HTTPGone(text="No matching Samsung Find setup session")

        try:
            await hass.config_entries.flow.async_configure(
                flow_id=matched_flow_id,
                user_input={"redirect_uri": redirect_uri},
            )
        except UnknownFlow as exc:
            async_remove_auth_flow(hass, matched_flow_id)
            raise web.HTTPGone(text="Samsung Find setup flow no longer exists") from exc

        return web.json_response({"ok": True, "status": "accepted"})
