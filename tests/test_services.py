"""Tests for the homebears.add_shopping_item and homebears.complete_chore actions."""

from typing import Any

import pytest
import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homebears.const import DOMAIN

from .conftest import CIRCLE_URL, HOUSEHOLD_URL, LIST_URL, chore, household, item, occurrence, page, setup_integration

CHORES_SENSOR = "sensor.home_chores_open_today"


def writes(aioclient_mock: AiohttpClientMocker) -> list[tuple[str, str, Any]]:
    return [(method, str(url), body) for method, url, body, _ in aioclient_mock.mock_calls if method != "GET"]


async def call(hass: HomeAssistant, service: str, data: dict[str, Any]) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_add_shopping_item(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(f"{LIST_URL}/items", status=201, json={"data": [item("i9", "Milk")]})
    await setup_integration(hass, config_entry)

    await call(
        hass,
        "add_shopping_item",
        {ATTR_ENTITY_ID: "todo.groceries", "item": "Milk", "quantity": "2", "op_id": "ha-milk-202611240800"},
    )

    assert writes(aioclient_mock) == [
        ("POST", f"{LIST_URL}/items", {"name": "Milk", "quantity": "2", "op_id": "ha-milk-202611240800"})
    ]


async def test_add_shopping_item_rejects_an_entity_of_another_integration(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)

    with pytest.raises(ServiceValidationError):
        await call(hass, "add_shopping_item", {ATTR_ENTITY_ID: "todo.shopping_list", "item": "Milk"})


async def test_complete_a_scheduled_chore_by_name_ticks_off_todays_occurrence(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(f"{HOUSEHOLD_URL}/occurrences/o2/complete", json={"data": {}})
    await setup_integration(hass, config_entry)

    await call(hass, "complete_chore", {ATTR_ENTITY_ID: CHORES_SENSOR, "chore": "take out the bins"})

    assert writes(aioclient_mock) == [("POST", f"{HOUSEHOLD_URL}/occurrences/o2/complete", {})]


async def test_complete_an_on_demand_chore_by_id_with_credit(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(f"{HOUSEHOLD_URL}/cleaning-tasks/t3/complete", status=201, json={"data": {}})
    await setup_integration(hass, config_entry)

    await call(hass, "complete_chore", {"chore": "t3", "credited_user_id": "u2"})

    assert writes(aioclient_mock) == [
        ("POST", f"{HOUSEHOLD_URL}/cleaning-tasks/t3/complete", {"credited_user_id": "u2"})
    ]


async def test_complete_by_occurrence_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(f"{HOUSEHOLD_URL}/occurrences/o1/complete", json={"data": {}})
    await setup_integration(hass, config_entry)

    await call(hass, "complete_chore", {ATTR_ENTITY_ID: CHORES_SENSOR, "occurrence_id": "o1"})

    assert writes(aioclient_mock) == [("POST", f"{HOUSEHOLD_URL}/occurrences/o1/complete", {})]


async def test_a_scheduled_chore_that_is_not_open_today_is_an_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{HOUSEHOLD_URL}/cleaning-tasks", json=page([chore("t5", "Mop the floor")]))
    aioclient_mock.get(f"{HOUSEHOLD_URL}/occurrences", json=page([]))
    aioclient_mock.get(f"{CIRCLE_URL}/households", json=page([household()]))

    with pytest.raises(ServiceValidationError, match="not open today"):
        await call(hass, "complete_chore", {ATTR_ENTITY_ID: CHORES_SENSOR, "chore": "Mop the floor"})

    assert writes(aioclient_mock) == []


async def test_an_unknown_chore_is_an_error(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    with pytest.raises(ServiceValidationError, match="Water the plants"):
        await call(hass, "complete_chore", {ATTR_ENTITY_ID: CHORES_SENSOR, "chore": "Water the plants"})


async def test_chore_and_occurrence_together_are_refused(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)

    with pytest.raises(vol.Invalid):
        await call(hass, "complete_chore", {"chore": "t1", "occurrence_id": "o1"})


async def test_by_name_prefers_the_same_named_chore_that_is_open_today(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{HOUSEHOLD_URL}/cleaning-tasks", json=page([chore("t7", "Vacuum"), chore("t8", "Vacuum")]))
    aioclient_mock.get(f"{HOUSEHOLD_URL}/occurrences", json=page([occurrence("o8", "t8", "Vacuum")]))
    aioclient_mock.get(f"{CIRCLE_URL}/households", json=page([household()]))
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists", json=page([]))
    aioclient_mock.post(f"{HOUSEHOLD_URL}/occurrences/o8/complete", json={"data": {}})

    await call(hass, "complete_chore", {"chore": "Vacuum"})

    assert writes(aioclient_mock) == [("POST", f"{HOUSEHOLD_URL}/occurrences/o8/complete", {})]
