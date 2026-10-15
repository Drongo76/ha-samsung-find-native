from __future__ import annotations

import secrets
import time
import urllib.parse
from typing import Any, Callable

from aiohttp import ClientSession

from .const import (
    AUTH_CLIENT_ID,
    CONF_AUTH_SERVER_URL,
    CONF_FIND_TOKEN,
    CONF_IOT_TOKEN,
    CONF_LOGIN_ID,
    CONF_PHYSICAL_ADDRESS,
    CONF_USERAUTH_TOKEN,
    CONF_USER_ID,
    ENTRY_POINT_URL,
    FIND_CLIENT_ID,
    FIND_SCOPE,
    IOT_CLIENT_ID,
    IOT_SCOPE,
    REDIRECT_URI,
)
from .crypto import code_challenge, decrypt_auth_value, encrypt_svc_param, random_urlsafe


class SamsungAuthError(Exception):
    pass


class SamsungAuthTemporaryError(SamsungAuthError):
    pass


def _trusted_auth_server_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise SamsungAuthError(f"Samsung returned a non-HTTPS authentication server (scheme={parsed.scheme!r}, host={host!r})")
    if not (host == "account.samsung.com" or host.endswith(".samsungosp.com")):
        raise SamsungAuthError(f"Samsung returned an untrusted authentication server (scheme={parsed.scheme!r}, host={host!r})")
    return f"https://{parsed.netloc}"


async def _json_response(response, step: str) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        if response.status >= 500 or response.status == 429:
            raise SamsungAuthTemporaryError(f'{step} failed with HTTP {response.status}')
        raise SamsungAuthError(f"{step} failed with HTTP {response.status}")
    try:
        return await response.json(content_type=None)
    except Exception as exc:
        raise SamsungAuthError(f"{step} returned invalid JSON") from exc


class SamsungAuthBootstrap:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_start(
        self,
        country: str,
        locale: str,
        *,
        device_id: str | None = None,
        manufacturer: str = "samsung",
        model: str = "SM-S928B",
        os_version: str = "36",
    ) -> tuple[str, dict[str, Any]]:
        async with self._session.get(
            ENTRY_POINT_URL, allow_redirects=False
        ) as response:
            entry = await _json_response(response, "Samsung entry point")

        device_id = device_id or secrets.token_hex(8)
        state = random_urlsafe(15)[:20]
        verifier = random_urlsafe(32)[:43]
        payload = {
            "clientId": AUTH_CLIENT_ID,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "competitorDeviceYNFlag": "N" if manufacturer.lower() == "samsung" else "Y",
            "countryCode": country.lower(),
            "deviceInfo": f"{manufacturer}|com.android.chrome",
            "deviceModelID": model,
            "deviceName": f"{manufacturer} {model}",
            "deviceOSVersion": os_version,
            "devicePhysicalAddressText": f"ANID:{device_id}",
            "deviceType": "APP",
            "deviceUniqueID": device_id,
            "redirect_uri": REDIRECT_URI,
            "replaceableClientConnectYN": "N",
            "replaceableClientId": "",
            "replaceableDevicePhysicalAddressText": "",
            "responseEncryptionType": "1",
            "responseEncryptionYNFlag": "Y",
            "scope": "",
            "state": state,
            "svcIptLgnID": "",
            "iosYNFlag": "Y",
        }
        encrypted = encrypt_svc_param(
            payload, int(entry["chkDoNum"]), str(entry["pkiPublicKey"])
        )
        login_url = (
            f"{entry['signInURI']}?locale={urllib.parse.quote(locale)}"
            f"&svcParam={encrypted}&mode=C"
        )
        pending = {
            "state": state,
            "code_verifier": verifier,
            "device_id": device_id,
            "created_at": int(time.time()),
        }
        return login_url, pending

    def _decode_callback(
        self, redirect_uri: str, pending: dict[str, Any]
    ) -> tuple[str, str, str]:
        age = time.time() - float(pending.get("created_at", 0))
        if age < -60 or age > 900:
            raise SamsungAuthError("Samsung authentication has expired")

        try:
            actual = urllib.parse.urlsplit(redirect_uri)
            expected = urllib.parse.urlsplit(REDIRECT_URI)
        except (TypeError, ValueError) as exc:
            raise SamsungAuthError("Unexpected Samsung callback URI") from exc

        if (
            actual.scheme.lower(),
            actual.netloc.lower(),
            actual.path,
        ) != (
            expected.scheme.lower(),
            expected.netloc.lower(),
            expected.path,
        ):
            raise SamsungAuthError("Unexpected Samsung callback URI")

        params = urllib.parse.parse_qs(actual.query)
        if actual.fragment:
            params.update(urllib.parse.parse_qs(actual.fragment))

        def one(name: str) -> str:
            value = params.get(name, [""])[0]
            if not value:
                raise SamsungAuthError(f"Samsung callback is missing {name}")
            return value

        try:
            response_key = decrypt_auth_value(one("state"), str(pending["state"]))
            auth_server = _trusted_auth_server_url(
                decrypt_auth_value(one("auth_server_url"), response_key)
            )
            code = decrypt_auth_value(one("code"), response_key)
            login_id = decrypt_auth_value(one("retValue"), response_key)
        except SamsungAuthError:
            raise
        except Exception as exc:
            raise SamsungAuthError("Unable to decrypt Samsung callback") from exc

        return auth_server, code, login_id

    def callback_matches(
        self, redirect_uri: str, pending: dict[str, Any]
    ) -> bool:
        try:
            self._decode_callback(redirect_uri, pending)
        except SamsungAuthError:
            return False
        return True

    async def async_complete(
        self, redirect_uri: str, pending: dict[str, Any]
    ) -> dict[str, Any]:
        auth_server, code, login_id = self._decode_callback(redirect_uri, pending)

        async with self._session.post(
            f"{auth_server}/auth/oauth2/authenticate",
            data={
                "grant_type": "authorization_code",
                "serviceType": "M",
                "client_id": AUTH_CLIENT_ID,
                "code": code,
                "code_verifier": pending["code_verifier"],
                "username": login_id,
                "physical_address_text": pending["device_id"],
            },
            allow_redirects=False,
        ) as response:
            master = await _json_response(response, "Samsung master authentication")

        userauth_token = master.get("userauth_token") or master.get("userAuthToken")
        user_id = master.get("userId") or master.get("user_id")
        if not userauth_token or not user_id:
            raise SamsungAuthError("Samsung omitted master credentials")

        find_token = await self._async_issue_token(
            auth_server,
            str(userauth_token),
            str(pending["device_id"]),
            login_id,
            FIND_CLIENT_ID,
            FIND_SCOPE,
        )
        iot_token = await self._async_issue_token(
            auth_server,
            str(userauth_token),
            str(pending["device_id"]),
            login_id,
            IOT_CLIENT_ID,
            IOT_SCOPE,
        )
        return {
            CONF_AUTH_SERVER_URL: auth_server,
            CONF_USERAUTH_TOKEN: str(userauth_token),
            CONF_USER_ID: str(user_id),
            CONF_LOGIN_ID: login_id,
            CONF_PHYSICAL_ADDRESS: str(pending["device_id"]),
            CONF_FIND_TOKEN: find_token,
            CONF_IOT_TOKEN: iot_token,
        }

    async def _async_issue_token(
        self,
        auth_server: str,
        userauth_token: str,
        device_id: str,
        login_id: str,
        client_id: str,
        scope: str,
    ) -> dict[str, Any]:
        verifier = random_urlsafe(32)[:43]
        params = {
            "response_type": "code",
            "serviceType": "M",
            "client_id": client_id,
            "code_challenge_method": "S256",
            "childAccountSupported": "Y",
            "userauth_token": userauth_token,
            "code_challenge": code_challenge(verifier),
            "physical_address_text": device_id,
            "scope": scope,
            "login_id": login_id,
        }
        async with self._session.get(
            f"{auth_server}/auth/oauth2/v2/authorize",
            params=params,
            allow_redirects=False,
        ) as response:
            auth_data = await _json_response(response, "Samsung scoped authorization")
        code = auth_data.get("code")
        if not code and auth_data.get("privacyAccepted") == "N":
            params.pop("login_id", None)
            async with self._session.get(
                f"{auth_server}/auth/oauth2/v2/authorize",
                params=params,
                allow_redirects=False,
            ) as response:
                auth_data = await _json_response(
                    response, "Samsung scoped authorization"
                )
            code = auth_data.get("code")
        if not code:
            raise SamsungAuthError("Samsung omitted scoped authorization code")

        async with self._session.post(
            f"{auth_server}/auth/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "physical_address_text": device_id,
            },
            allow_redirects=False,
        ) as response:
            token = await _json_response(response, "Samsung token exchange")
        return self._normalize_token(token)

    @staticmethod
    def _normalize_token(token: dict[str, Any]) -> dict[str, Any]:
        if not token.get("access_token") or not token.get("refresh_token"):
            raise SamsungAuthError("Samsung token response is incomplete")
        result = dict(token)
        now = int(time.time())
        result["obtained_at"] = now
        result["expires_at"] = now + int(token.get("expires_in", 3600))
        return result


class SamsungAuthManager:
    def __init__(
        self,
        session: ClientSession,
        data: dict[str, Any],
        save_data: Callable[[dict[str, Any]], None],
    ) -> None:
        self._session = session
        self._data = dict(data)
        self._save_data = save_data

    @property
    def user_id(self) -> str:
        return str(self._data[CONF_USER_ID])

    @property
    def login_id(self) -> str:
        return str(self._data[CONF_LOGIN_ID])

    @property
    def device_id(self) -> str:
        return str(self._data[CONF_PHYSICAL_ADDRESS])

    @property
    def auth_server_url(self) -> str:
        return str(self._data[CONF_AUTH_SERVER_URL])

    async def async_access_token(self, kind: str, force_refresh: bool = False) -> str:
        token_key = CONF_FIND_TOKEN if kind == "find" else CONF_IOT_TOKEN
        client_id = FIND_CLIENT_ID if kind == "find" else IOT_CLIENT_ID
        scope = FIND_SCOPE if kind == "find" else IOT_SCOPE
        token = dict(self._data.get(token_key) or {})
        if (
            not force_refresh
            and token.get("access_token")
            and float(token.get("expires_at", 0)) > time.time() + 120
        ):
            return str(token["access_token"])

        new_token = await self._async_refresh(token, client_id)
        if new_token is None:
            bootstrap = SamsungAuthBootstrap(self._session)
            new_token = await bootstrap._async_issue_token(
                self.auth_server_url,
                str(self._data[CONF_USERAUTH_TOKEN]),
                self.device_id,
                self.login_id,
                client_id,
                scope,
            )

        self._data[token_key] = new_token
        self._save_data(dict(self._data))
        return str(new_token["access_token"])

    async def _async_refresh(
        self, token: dict[str, Any], client_id: str
    ) -> dict[str, Any] | None:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            return None
        async with self._session.post(
            f"{self.auth_server_url}/auth/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                return None
            try:
                data = await response.json(content_type=None)
            except Exception:
                return None
        try:
            return SamsungAuthBootstrap._normalize_token(data)
        except SamsungAuthError:
            return None
