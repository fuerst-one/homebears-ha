"""Tests for the Homebears shopping list as a Home Assistant to-do list."""

from typing import Any

import pytest
from homeassistant.components.todo import (
    ATTR_DESCRIPTION,
    ATTR_ITEM,
    ATTR_RENAME,
    ATTR_STATUS,
    TodoItem,
    TodoItemStatus,
    TodoServices,
)
from homeassistant.components.todo import (
    DOMAIN as TODO_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import LIST_URL, item, setup_integration

ENTITY_ID = "todo.groceries"


async def call(hass: HomeAssistant, service: str, data: dict[str, Any], response: bool = False) -> Any:
    return await hass.services.async_call(
        TODO_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID, **data}, blocking=True, return_response=response
    )


def writes(aioclient_mock: AiohttpClientMocker) -> list[tuple[str, str, Any]]:
    return [(method, str(url), body) for method, url, body, _ in aioclient_mock.mock_calls if method != "GET"]


async def test_lists_the_items(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    assert hass.states.get(ENTITY_ID).state == "2"
    response = await call(hass, TodoServices.GET_ITEMS, {}, response=True)

    assert response[ENTITY_ID]["items"] == [
        {"uid": "i1", "summary": "Eggs", "status": "needs_action"},
        {"uid": "i2", "summary": "Oat milk", "status": "needs_action", "description": "2"},
        {"uid": "i3", "summary": "Bread", "status": "completed"},
    ]


async def test_adding_an_item_sends_the_description_as_quantity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(f"{LIST_URL}/items", status=201, json={"data": [item("i9", "Butter", "250 g")]})
    await setup_integration(hass, config_entry)

    await call(hass, TodoServices.ADD_ITEM, {ATTR_ITEM: "Butter", ATTR_DESCRIPTION: "250 g"})

    assert writes(aioclient_mock) == [("POST", f"{LIST_URL}/items", {"name": "Butter", "quantity": "250 g"})]


async def test_completing_and_reopening_items(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(f"{LIST_URL}/items/i1/check", json={"data": []})
    aioclient_mock.post(f"{LIST_URL}/items/i3/uncheck", json={"data": []})
    await setup_integration(hass, config_entry)

    await call(hass, TodoServices.UPDATE_ITEM, {ATTR_ITEM: "Eggs", ATTR_STATUS: "completed"})
    await call(hass, TodoServices.UPDATE_ITEM, {ATTR_ITEM: "i3", ATTR_STATUS: "needs_action"})

    assert writes(aioclient_mock) == [
        ("POST", f"{LIST_URL}/items/i1/check", None),
        ("POST", f"{LIST_URL}/items/i3/uncheck", None),
    ]


async def test_renaming_and_changing_the_quantity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.patch(f"{LIST_URL}/items/i2", json={"data": []})
    await setup_integration(hass, config_entry)

    await call(hass, TodoServices.UPDATE_ITEM, {ATTR_ITEM: "i2", ATTR_RENAME: "Soy milk", ATTR_DESCRIPTION: "3"})

    assert writes(aioclient_mock) == [("PATCH", f"{LIST_URL}/items/i2", {"name": "Soy milk", "quantity": "3"})]


async def test_clearing_the_description_clears_the_quantity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.patch(f"{LIST_URL}/items/i2", json={"data": []})
    await setup_integration(hass, config_entry)

    await call(hass, TodoServices.UPDATE_ITEM, {ATTR_ITEM: "i2", ATTR_DESCRIPTION: None})

    assert writes(aioclient_mock) == [("PATCH", f"{LIST_URL}/items/i2", {"quantity": None})]


async def test_removing_items(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.delete(f"{LIST_URL}/items/i1", status=204)
    aioclient_mock.delete(f"{LIST_URL}/items/i3", status=204)
    await setup_integration(hass, config_entry)

    await call(hass, TodoServices.REMOVE_ITEM, {ATTR_ITEM: ["i1", "Bread"]})

    assert writes(aioclient_mock) == [
        ("DELETE", f"{LIST_URL}/items/i1", None),
        ("DELETE", f"{LIST_URL}/items/i3", None),
    ]


async def test_api_errors_surface_to_the_caller(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.post(
        f"{LIST_URL}/items", status=422, json={"error": {"code": "validation_failed", "message": "Too long."}}
    )
    await setup_integration(hass, config_entry)

    with pytest.raises(HomeAssistantError, match=r"Too long\."):
        await call(hass, TodoServices.ADD_ITEM, {ATTR_ITEM: "x" * 300})


async def test_a_delete_of_an_item_already_gone_carries_on(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_api, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.delete(f"{LIST_URL}/items/i1", status=404, json={"error": {"code": "not_found", "message": "Gone."}})
    aioclient_mock.delete(f"{LIST_URL}/items/i3", status=204)
    await setup_integration(hass, config_entry)

    await call(hass, TodoServices.REMOVE_ITEM, {ATTR_ITEM: ["i1", "i3"]})

    assert writes(aioclient_mock) == [
        ("DELETE", f"{LIST_URL}/items/i1", None),
        ("DELETE", f"{LIST_URL}/items/i3", None),
    ]


async def test_updating_an_item_unknown_to_the_entity_is_a_validation_error(
    hass: HomeAssistant, mock_api, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    entity = hass.data["entity_components"]["todo"].get_entity(ENTITY_ID)

    with pytest.raises(ServiceValidationError):
        await entity.async_update_todo_item(TodoItem(uid="gone", summary="Gone", status=TodoItemStatus.COMPLETED))
