"""Tests for the Homebears config, options and reauth flows."""

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homebears.const import (
    CONF_BASE_URL,
    CONF_CIRCLE_ID,
    CONF_HOUSEHOLDS,
    CONF_SHOPPING_LISTS,
    DEFAULT_BASE_URL,
    DOMAIN,
)

from .conftest import (
    API_KEY,
    BASE_URL,
    CIRCLE_ID,
    CIRCLE_URL,
    HOUSEHOLD_ID,
    LIST_ID,
    OTHER_LIST_ID,
    circle,
    page,
    setup_integration,
)

SCOPE_ERROR = {"error": {"code": "insufficient_scope", "message": "Missing scope.", "details": {"required_scope": "x"}}}


async def start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def submit_key(hass: HomeAssistant, flow_id: str, key: str = API_KEY) -> dict:
    return await hass.config_entries.flow.async_configure(flow_id, {CONF_BASE_URL: BASE_URL, CONF_API_KEY: key})


def selector_values(result: dict, field: str) -> list[str]:
    for key, validator in result["data_schema"].schema.items():
        if key == field:
            return [option["value"] for option in validator.config["options"]]
    raise AssertionError(f"{field} is not in the form")


def form_fields(result: dict) -> set[str]:
    return {str(key) for key in result["data_schema"].schema}


async def test_user_flow_with_one_circle_goes_straight_to_picking(hass: HomeAssistant, mock_api) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    defaults = {str(key): key.default() for key in result["data_schema"].schema if callable(key.default)}
    assert defaults[CONF_BASE_URL] == DEFAULT_BASE_URL

    result = await submit_key(hass, result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select"
    assert selector_values(result, CONF_SHOPPING_LISTS) == [LIST_ID, OTHER_LIST_ID]
    assert selector_values(result, CONF_HOUSEHOLDS) == [HOUSEHOLD_ID]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHOPPING_LISTS: [LIST_ID], CONF_HOUSEHOLDS: [HOUSEHOLD_ID]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Flat"
    assert result["result"].unique_id == CIRCLE_ID
    assert result["data"] == {CONF_BASE_URL: BASE_URL, CONF_API_KEY: API_KEY, CONF_CIRCLE_ID: CIRCLE_ID}
    assert result["options"] == {CONF_SHOPPING_LISTS: [LIST_ID], CONF_HOUSEHOLDS: [HOUSEHOLD_ID]}


async def test_user_flow_asks_for_the_circle_when_there_are_several(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([circle("c0", "Parents"), circle()]))
    aioclient_mock.get(f"{BASE_URL}/circles/c0/households", json=page([]))
    aioclient_mock.get(f"{CIRCLE_URL}/households", json=page([]))
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", json=page([]))

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert result["step_id"] == "circle"
    assert selector_values(result, CONF_CIRCLE_ID) == ["c0", CIRCLE_ID]


async def test_wrong_key_shows_invalid_auth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", status=401, json={"error": {"code": "unauthenticated"}})

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_unreachable_server_shows_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", exc=TimeoutError())

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert result["errors"] == {"base": "cannot_connect"}


async def test_key_that_is_not_a_homebears_key_is_refused_locally(hass: HomeAssistant) -> None:
    result = await submit_key(hass, (await start(hass))["flow_id"], key="Bearer something")

    assert result["errors"] == {CONF_API_KEY: "invalid_key_format"}


async def test_no_circle_aborts(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([]))

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_circles"


async def test_same_circle_twice_aborts(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_picking_nothing_is_an_error(hass: HomeAssistant, mock_api) -> None:
    result = await submit_key(hass, (await start(hass))["flow_id"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHOPPING_LISTS: [], CONF_HOUSEHOLDS: []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "nothing_selected"}


async def test_without_households_scope_only_lists_are_offered(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([circle()]))
    aioclient_mock.get(f"{CIRCLE_URL}/households", status=403, json=SCOPE_ERROR)
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", json=page([{"id": LIST_ID, "name": "Groceries"}]))

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert form_fields(result) == {CONF_SHOPPING_LISTS}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SHOPPING_LISTS: [LIST_ID]})
    assert result["options"] == {CONF_SHOPPING_LISTS: [LIST_ID], CONF_HOUSEHOLDS: []}


async def test_key_without_any_usable_scope_aborts(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([circle()]))
    aioclient_mock.get(f"{CIRCLE_URL}/households", status=403, json=SCOPE_ERROR)
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", status=403, json=SCOPE_ERROR)

    result = await submit_key(hass, (await start(hass))["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "missing_scopes"


async def test_options_flow_changes_the_selection(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHOPPING_LISTS: [LIST_ID, OTHER_LIST_ID], CONF_HOUSEHOLDS: []}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SHOPPING_LISTS: [LIST_ID, OTHER_LIST_ID], CONF_HOUSEHOLDS: []}
    assert hass.states.get("todo.hardware") is not None


async def test_reauth_replaces_the_key(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)

    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "hb_new_key"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "hb_new_key"


async def test_reauth_with_a_key_for_another_circle_is_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([circle("c9", "Elsewhere")]))
    config_entry.add_to_hass(hass)

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "hb_other"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_circle"}
    assert config_entry.data[CONF_API_KEY] == API_KEY


async def test_options_flow_works_while_the_entry_is_not_loaded(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert selector_values(result, CONF_SHOPPING_LISTS) == [LIST_ID, OTHER_LIST_ID]


async def test_options_flow_drops_lists_that_no_longer_exist(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SHOPPING_LISTS: [LIST_ID, "deleted"], CONF_HOUSEHOLDS: [HOUSEHOLD_ID]}
    )

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    suggested = {str(key): key.description["suggested_value"] for key in result["data_schema"].schema}

    assert suggested[CONF_SHOPPING_LISTS] == [LIST_ID]


async def test_options_flow_with_a_revoked_key_aborts_with_invalid_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", status=401, json={"error": {"code": "unauthenticated"}})
    aioclient_mock.get(f"{CIRCLE_URL}/households", status=401, json={"error": {"code": "unauthenticated"}})
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


async def test_reauth_of_a_loaded_entry_needs_no_update_listener(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "hb_new_key"})
    await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert config_entry.update_listeners == []
    assert config_entry.state is ConfigEntryState.LOADED


async def test_an_address_that_is_not_http_is_refused(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_configure(
        (await start(hass))["flow_id"], {CONF_BASE_URL: "ftp://example.com", CONF_API_KEY: API_KEY}
    )

    assert result["errors"] == {CONF_BASE_URL: "invalid_url"}


@pytest.mark.parametrize(
    "address",
    [
        "http://api.example.com/api/v1",
        "http://8.8.8.8/api/v1",
        "http://[::ffff:8.8.8.8]/api/v1",
        "http://[2002:808:808::1]/api/v1",
        "http://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/api/v1",
    ],
)
async def test_plain_http_to_a_public_host_is_refused(hass: HomeAssistant, address: str) -> None:
    result = await hass.config_entries.flow.async_configure(
        (await start(hass))["flow_id"], {CONF_BASE_URL: address, CONF_API_KEY: API_KEY}
    )

    assert result["errors"] == {CONF_BASE_URL: "insecure_url"}


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost:8100/api/v1",
        "http://127.0.0.1:8100/api/v1",
        "http://192.168.1.20/api/v1",
        "http://homebears.local/api/v1",
        "http://host.docker.internal:8100/api/v1",
    ],
)
async def test_plain_http_to_a_local_host_is_allowed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, address: str
) -> None:
    aioclient_mock.get(f"{address}/circles", json=page([]))

    result = await hass.config_entries.flow.async_configure(
        (await start(hass))["flow_id"], {CONF_BASE_URL: address, CONF_API_KEY: API_KEY}
    )

    assert result["reason"] == "no_circles"
