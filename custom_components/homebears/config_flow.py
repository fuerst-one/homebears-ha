"""Config flow: API key, then circle, then which lists and households to show. No ids to look up by hand."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from yarl import URL

from .api import HomebearsAuthError, HomebearsClient, HomebearsConnectionError, HomebearsError, HomebearsScopeError
from .const import (
    CONF_BASE_URL,
    CONF_CIRCLE_ID,
    CONF_HOUSEHOLDS,
    CONF_SHOPPING_LISTS,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from .coordinator import HomebearsConfigEntry

_LOGGER = logging.getLogger(__name__)

LOCAL_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa")
KEY_PREFIX = "hb_"
KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

type Choices = list[SelectOptionDict] | None


class HomebearsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._client: HomebearsClient | None = None
        self._data: dict[str, Any] = {}
        self._circles: dict[str, str] = {}
        self._lists: Choices = None
        self._households: Choices = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: HomebearsConfigEntry) -> HomebearsOptionsFlow:
        return HomebearsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].strip().rstrip("/")
            api_key = user_input[CONF_API_KEY].strip()
            if URL(base_url).scheme not in ("http", "https"):
                errors[CONF_BASE_URL] = "invalid_url"
            elif not _keeps_the_key_private(URL(base_url)):
                errors[CONF_BASE_URL] = "insecure_url"
            elif not api_key.startswith(KEY_PREFIX):
                errors[CONF_API_KEY] = "invalid_key_format"
            else:
                client = HomebearsClient(async_get_clientsession(self.hass), base_url, api_key)
                circles, errors = await _fetch_circles(client)
                if not errors:
                    if not circles:
                        return self.async_abort(reason="no_circles")
                    self._client = client
                    self._data = {CONF_BASE_URL: base_url, CONF_API_KEY: api_key}
                    self._circles = {c["id"]: c["name"] for c in circles}
                    if len(circles) == 1:
                        return await self._async_pick_circle(circles[0]["id"])
                    return await self.async_step_circle()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                        vol.Required(CONF_API_KEY): KEY_SELECTOR,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_circle(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_pick_circle(user_input[CONF_CIRCLE_ID])
        options = [SelectOptionDict(value=cid, label=name) for cid, name in self._circles.items()]
        return self.async_show_form(
            step_id="circle",
            data_schema=vol.Schema(
                {vol.Required(CONF_CIRCLE_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def _async_pick_circle(self, circle_id: str) -> ConfigFlowResult:
        await self.async_set_unique_id(circle_id)
        self._abort_if_unique_id_configured()
        self._data[CONF_CIRCLE_ID] = circle_id
        assert self._client is not None
        try:
            self._lists, self._households = await _fetch_choices(self._client, circle_id)
        except HomebearsError:
            _LOGGER.exception("Could not list the shopping lists and households of circle %s", circle_id)
            return self.async_abort(reason="cannot_connect")
        if self._lists is None and self._households is None:
            return self.async_abort(reason="missing_scopes")
        return await self.async_step_select()

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options = _selection(user_input)
            if any(options.values()):
                return self.async_create_entry(
                    title=self._circles[self._data[CONF_CIRCLE_ID]], data=self._data, options=options
                )
            errors["base"] = "nothing_selected"
        return self.async_show_form(
            step_id="select", data_schema=_selection_schema(self._lists, self._households), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if not api_key.startswith(KEY_PREFIX):
                errors[CONF_API_KEY] = "invalid_key_format"
            else:
                client = HomebearsClient(async_get_clientsession(self.hass), entry.data[CONF_BASE_URL], api_key)
                circles, errors = await _fetch_circles(client)
                if not errors and entry.data[CONF_CIRCLE_ID] not in {c["id"] for c in circles}:
                    errors["base"] = "wrong_circle"
                if not errors:
                    return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: api_key})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): KEY_SELECTOR}),
            description_placeholders={"circle": entry.title},
            errors=errors,
        )


class HomebearsOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options = _selection(user_input)
            if any(options.values()):
                return self.async_create_entry(data=options)
            errors["base"] = "nothing_selected"

        # Built from the entry, not runtime_data: Configure must work while setup fails, which is when it is needed.
        entry = self.config_entry
        client = HomebearsClient(
            async_get_clientsession(self.hass), entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY]
        )
        try:
            lists, households = await _fetch_choices(client, entry.data[CONF_CIRCLE_ID])
        except HomebearsAuthError:
            return self.async_abort(reason="invalid_auth")
        except HomebearsError:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _selection_schema(lists, households), _still_offered(user_input or entry.options, lists, households)
            ),
            errors=errors,
        )


async def _fetch_circles(client: HomebearsClient) -> tuple[list[dict[str, Any]], dict[str, str]]:
    try:
        return await client.get_circles(), {}
    except HomebearsAuthError:
        return [], {"base": "invalid_auth"}
    except HomebearsConnectionError:
        return [], {"base": "cannot_connect"}
    except HomebearsError:
        _LOGGER.exception("Unexpected answer from Homebears")
        return [], {"base": "unknown"}


async def _fetch_choices(client: HomebearsClient, circle_id: str) -> tuple[Choices, Choices]:
    """Shopping lists and households of the circle as choices; None for what the key may not read."""

    async def choices(fetch) -> Choices:
        try:
            rows = await fetch(circle_id)
        except HomebearsScopeError:
            return None
        return [SelectOptionDict(value=row["id"], label=row["name"]) for row in rows] or None

    return await choices(client.get_shopping_lists), await choices(client.get_households)


def _selection_schema(lists: Choices, households: Choices) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for key, options in ((CONF_SHOPPING_LISTS, lists), (CONF_HOUSEHOLDS, households)):
        if options:
            fields[vol.Optional(key, default=[])] = SelectSelector(
                SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
            )
    return vol.Schema(fields)


def _selection(user_input: dict[str, Any]) -> dict[str, list[str]]:
    return {key: list(user_input.get(key, [])) for key in (CONF_SHOPPING_LISTS, CONF_HOUSEHOLDS)}


def _still_offered(selection: Mapping[str, Any], lists: Choices, households: Choices) -> dict[str, list[str]]:
    """The selection without lists and households deleted since; the selector would refuse them on submit."""
    offered = {
        CONF_SHOPPING_LISTS: {option["value"] for option in lists or []},
        CONF_HOUSEHOLDS: {option["value"] for option in households or []},
    }
    return {key: [i for i in selection.get(key, []) if i in values] for key, values in offered.items() if values}


def _keeps_the_key_private(url: URL) -> bool:
    """https anywhere; plain http only within the home network, since the key would travel in cleartext."""
    if url.scheme == "https":
        return True
    host = (url.host or "").lower()
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local
