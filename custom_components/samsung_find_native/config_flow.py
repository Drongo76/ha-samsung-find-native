from __future__ import annotations

import secrets
import urllib.parse
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError

from .auth import SamsungAuthBootstrap, SamsungAuthError
from .callback import (
    START_PATH,
    async_get_auth_flow,
    async_register_auth_flow,
    async_remove_auth_flow,
    ensure_callback_views,
    external_base_url,
)
from .const import (
    BRIDGE_APK_URL,
    CONF_OFFLINE_AFTER,
    DEFAULT_OFFLINE_AFTER,
    MAX_OFFLINE_AFTER,
    MIN_OFFLINE_AFTER,
    CONF_COUNTRY,
    CONF_LANGUAGE,
    CONF_PIN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_COUNTRY,
    DEFAULT_LANGUAGE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)


class SamsungFindConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 4

    def __init__(self) -> None:
        self._start_url: str | None = None
        self._redirect_uri: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                description_placeholders={"apk_url": BRIDGE_APK_URL},
            )
        return await self._async_start_authorize()

    async def _async_start_authorize(self) -> config_entries.ConfigFlowResult:
        ensure_callback_views(self.hass)

        try:
            base_url = external_base_url(self.hass)
        except NoURLAvailableError:
            return self.async_abort(reason="no_external_url")

        nonce = secrets.token_urlsafe(32)
        async_register_auth_flow(
            self.hass,
            self.flow_id,
            nonce=nonce,
        )
        self._start_url = (
            f"{base_url}{START_PATH}?"
            + urllib.parse.urlencode(
                {
                    "flow_id": self.flow_id,
                    "nonce": nonce,
                }
            )
        )
        return self.async_external_step(
            step_id="authorize",
            url=self._start_url,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_user()

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is None:
            if self._start_url is None:
                return await self._async_start_authorize()
            return self.async_external_step(
                step_id="authorize",
                url=self._start_url,
            )

        redirect_uri = str(user_input.get("redirect_uri") or "").strip()
        if not redirect_uri:
            return self.async_abort(reason="invalid_auth")

        self._redirect_uri = redirect_uri
        return self.async_external_step_done(next_step_id="creation")

    async def async_step_creation(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if self._redirect_uri is None:
            async_remove_auth_flow(self.hass, self.flow_id)
            return self.async_abort(reason="invalid_auth")

        record = async_get_auth_flow(self.hass, self.flow_id)
        pending = record.get("pending") if record else None
        if not isinstance(pending, dict):
            async_remove_auth_flow(self.hass, self.flow_id)
            return self.async_abort(reason="auth_expired")

        auth = SamsungAuthBootstrap(async_get_clientsession(self.hass))
        try:
            auth_data = await auth.async_complete(self._redirect_uri, pending)
        except SamsungAuthError as exc:
            async_remove_auth_flow(self.hass, self.flow_id)
            reason = "auth_expired" if "expired" in str(exc).lower() else "invalid_auth"
            return self.async_abort(reason=reason)
        except Exception:
            async_remove_auth_flow(self.hass, self.flow_id)
            return self.async_abort(reason="cannot_connect")

        async_remove_auth_flow(self.hass, self.flow_id)

        user_id = str(auth_data.get("user_id") or "")
        await self.async_set_unique_id(user_id)
        if self.source == config_entries.SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason='wrong_account')
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=auth_data,
            )
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Samsung Find",
            data={
                CONF_COUNTRY: DEFAULT_COUNTRY,
                CONF_LANGUAGE: DEFAULT_LANGUAGE,
                **auth_data,
            },
            options={
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_PIN: "",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SamsungFindOptionsFlow:
        return SamsungFindOptionsFlow()


class SamsungFindOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=int(
                            self.config_entry.options.get(
                                CONF_UPDATE_INTERVAL,
                                DEFAULT_UPDATE_INTERVAL,
                            )
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                        ),
                    ),
                    vol.Required(
                        CONF_OFFLINE_AFTER,
                        default=int(
                            self.config_entry.options.get(
                                CONF_OFFLINE_AFTER,
                                DEFAULT_OFFLINE_AFTER,
                            )
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_OFFLINE_AFTER,
                            max=MAX_OFFLINE_AFTER,
                        ),
                    ),
                    vol.Optional(
                        CONF_PIN,
                        default=str(self.config_entry.options.get(CONF_PIN, "")),
                    ): str,
                }
            ),
        )
