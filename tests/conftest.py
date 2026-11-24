"""Shared fixtures for the Homebears tests."""

from collections.abc import Generator
from typing import Any

import pytest
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homebears.const import (
    CONF_BASE_URL,
    CONF_CIRCLE_ID,
    CONF_HOUSEHOLDS,
    CONF_SHOPPING_LISTS,
    DOMAIN,
)

BASE_URL = "https://api.homebears.test/api/v1"
API_KEY = "hb_test_key"
CIRCLE_ID = "c1"
HOUSEHOLD_ID = "h1"
LIST_ID = "l1"
OTHER_LIST_ID = "l2"
CIRCLE_URL = f"{BASE_URL}/circles/{CIRCLE_ID}"
LIST_URL = f"{CIRCLE_URL}/shopping-lists/{LIST_ID}"
HOUSEHOLD_URL = f"{CIRCLE_URL}/households/{HOUSEHOLD_ID}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    yield


def page(data: list[dict[str, Any]], page_number: int = 1, last_page: int = 1) -> dict[str, Any]:
    return {"data": data, "meta": {"page": page_number, "per_page": 100, "total": len(data), "last_page": last_page}}


def circle(circle_id: str = CIRCLE_ID, name: str = "Flat") -> dict[str, Any]:
    return {"id": circle_id, "name": name, "currency": "EUR", "my_role": "owner"}


def household(household_id: str = HOUSEHOLD_ID, name: str = "Home", timezone: str = "Europe/Berlin") -> dict[str, Any]:
    return {"id": household_id, "circle_id": CIRCLE_ID, "name": name, "icon": "house", "timezone": timezone}


def shopping_list(
    list_id: str = LIST_ID, name: str = "Groceries", open_count: int = 2, checked_count: int = 1
) -> dict[str, Any]:
    return {
        "id": list_id,
        "circle_id": CIRCLE_ID,
        "household_id": None,
        "name": name,
        "icon": None,
        "archived_at": None,
        "open_count": open_count,
        "checked_count": checked_count,
        "updated_at": "2026-11-24T08:00:00.000000Z",
    }


def item(item_id: str, name: str, quantity: str | None = None, checked: bool = False) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "quantity": quantity,
        "note": None,
        "categories": None,
        "checked_at": "2026-11-24T07:00:00.000000Z" if checked else None,
        "checked_by_user_id": None,
        "created_by_user_id": "u1",
    }


def occurrence(occurrence_id: str, task_id: str, name: str, due_on: str = "2026-11-24") -> dict[str, Any]:
    return {
        "id": occurrence_id,
        "cleaning_task_id": task_id,
        "household_id": HOUSEHOLD_ID,
        "due_on": due_on,
        "status": "open",
        "task": {"id": task_id, "name": name, "points": 1},
        "assignee": {"id": "u1", "name": "Anna"},
    }


def chore(task_id: str, name: str, on_demand: bool = False) -> dict[str, Any]:
    return {"id": task_id, "household_id": HOUSEHOLD_ID, "name": name, "on_demand": on_demand, "paused": False}


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Flat",
        unique_id=CIRCLE_ID,
        data={CONF_BASE_URL: BASE_URL, CONF_API_KEY: API_KEY, CONF_CIRCLE_ID: CIRCLE_ID},
        options={CONF_SHOPPING_LISTS: [LIST_ID], CONF_HOUSEHOLDS: [HOUSEHOLD_ID]},
    )


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """A circle with one household, two lists (one selected) and two chores due today."""
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([circle()]))
    aioclient_mock.get(f"{CIRCLE_URL}/households", json=page([household()]))
    aioclient_mock.get(
        f"{CIRCLE_URL}/shopping-lists",
        json=page([shopping_list(), shopping_list(OTHER_LIST_ID, "Hardware", 0, 0)]),
    )
    aioclient_mock.get(
        f"{LIST_URL}/items",
        json=page([item("i1", "Eggs"), item("i2", "Oat milk", quantity="2"), item("i3", "Bread", checked=True)]),
    )
    aioclient_mock.get(f"{CIRCLE_URL}/shopping-lists/{OTHER_LIST_ID}/items", json=page([]))
    aioclient_mock.get(
        f"{HOUSEHOLD_URL}/occurrences",
        json=page([occurrence("o1", "t1", "Empty the dishwasher"), occurrence("o2", "t2", "Take out the bins")]),
    )
    aioclient_mock.get(
        f"{HOUSEHOLD_URL}/cleaning-tasks",
        json=page(
            [chore("t1", "Empty the dishwasher"), chore("t2", "Take out the bins"), chore("t3", "Laundry", True)]
        ),
    )
    return aioclient_mock


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
