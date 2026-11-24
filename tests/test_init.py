"""Tests for setting up and unloading Homebears entries."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homebears.const import CONF_HOUSEHOLDS, CONF_SHOPPING_LISTS, DOMAIN

from .conftest import (
    BASE_URL,
    CIRCLE_URL,
    HOUSEHOLD_ID,
    HOUSEHOLD_URL,
    LIST_ID,
    LIST_URL,
    household,
    occurrence,
    page,
    setup_integration,
    shopping_list,
)


async def test_setup_and_unload(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("todo.groceries") is not None

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_revoked_key_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", status=401, json={"error": {"code": "unauthenticated"}})
    aioclient_mock.get(f"{CIRCLE_URL}/households", status=401, json={"error": {"code": "unauthenticated"}})
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_unreachable_api_retries_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", exc=TimeoutError())
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", exc=TimeoutError())
    aioclient_mock.get(f"{CIRCLE_URL}/households", exc=TimeoutError())
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_deleted_list_makes_its_entities_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_api,
    config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.groceries_open_items").state == "2"

    aioclient_mock.clear_requests()
    for url, body in mock_api_without_the_list():
        aioclient_mock.get(url, json=body)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.groceries_open_items").state == STATE_UNAVAILABLE
    assert hass.states.get("todo.groceries").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.home_chores_open_today").state == "2"


def mock_api_without_the_list() -> list[tuple[str, dict]]:
    return [
        (f"{CIRCLE_URL}/shopping-lists", page([shopping_list("l2", "Hardware")])),
        (f"{LIST_URL}/items", page([])),
        (f"{CIRCLE_URL}/households", page([household()])),
        (
            f"{HOUSEHOLD_URL}/occurrences",
            page([occurrence("o1", "t1", "Empty the dishwasher"), occurrence("o2", "t2", "Take out the bins")]),
        ),
    ]


async def test_a_missing_scope_only_drops_that_area(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(
        f"{CIRCLE_URL}/households",
        status=403,
        json={
            "error": {"code": "insufficient_scope", "message": "No.", "details": {"required_scope": "households:read"}}
        },
    )
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", json=page([shopping_list()]))
    aioclient_mock.get(f"{LIST_URL}/items", json=page([]))

    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("todo.groceries").state == "0"


async def test_deselected_lists_lose_their_device(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry, device_registry: dr.DeviceRegistry
) -> None:
    await setup_integration(hass, config_entry)
    assert device_registry.async_get_device_by_identifier((DOMAIN, LIST_ID), config_entry.entry_id) is not None

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SHOPPING_LISTS: [], CONF_HOUSEHOLDS: [HOUSEHOLD_ID]}
    )
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get_device_by_identifier((DOMAIN, LIST_ID), config_entry.entry_id) is None
    assert device_registry.async_get_device_by_identifier((DOMAIN, HOUSEHOLD_ID), config_entry.entry_id) is not None
