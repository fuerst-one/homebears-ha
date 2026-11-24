"""Tests for the Homebears REST client."""

from datetime import date

import pytest
from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homebears.api import (
    HomebearsApiError,
    HomebearsAuthError,
    HomebearsClient,
    HomebearsConnectionError,
    HomebearsScopeError,
)

from .conftest import (
    API_KEY,
    BASE_URL,
    CIRCLE_ID,
    CIRCLE_URL,
    HOUSEHOLD_ID,
    HOUSEHOLD_URL,
    LIST_ID,
    LIST_URL,
    circle,
    item,
    page,
)


@pytest.fixture
async def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> HomebearsClient:
    return HomebearsClient(async_get_clientsession(hass), BASE_URL + "/", API_KEY)


async def test_sends_the_key_as_bearer_token(client: HomebearsClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", json=page([circle()]))

    circles = await client.get_circles()

    assert circles == [circle()]
    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert str(url).startswith(f"{BASE_URL}/circles")
    assert headers["Authorization"] == f"Bearer {API_KEY}"
    assert headers["Accept"] == "application/json"


async def test_follows_every_page(client: HomebearsClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{LIST_URL}/items", params={"page": "1", "per_page": "100"}, json=page([item("i1", "Eggs")], 1, 2)
    )
    aioclient_mock.get(
        f"{LIST_URL}/items", params={"page": "2", "per_page": "100"}, json=page([item("i2", "Milk")], 2, 2)
    )

    items = await client.get_items(CIRCLE_ID, LIST_ID)

    assert [i["name"] for i in items] == ["Eggs", "Milk"]


async def test_reads_open_occurrences_of_one_day(client: HomebearsClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{HOUSEHOLD_URL}/occurrences", json=page([]))

    await client.get_open_occurrences(CIRCLE_ID, HOUSEHOLD_ID, date(2026, 11, 24))

    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["status"] == "open"
    assert url.query["from"] == "2026-11-24"
    assert url.query["to"] == "2026-11-24"


async def test_add_item_sends_only_the_given_fields(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{LIST_URL}/items", status=201, json={"data": [item("i9", "Milk")]})

    await client.add_item(CIRCLE_ID, LIST_ID, "Milk", quantity="2", op_id="ha-milk-1")
    await client.add_item(CIRCLE_ID, LIST_ID, "Eggs")

    assert aioclient_mock.mock_calls[0][2] == {"name": "Milk", "quantity": "2", "op_id": "ha-milk-1"}
    assert aioclient_mock.mock_calls[1][2] == {"name": "Eggs"}


async def test_complete_occurrence_credits_a_member(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{HOUSEHOLD_URL}/occurrences/o1/complete", json={"data": {}})

    await client.complete_occurrence(CIRCLE_ID, HOUSEHOLD_ID, "o1", credited_user_id="u2")

    assert aioclient_mock.mock_calls[0][2] == {"credited_user_id": "u2"}


async def test_unauthenticated_raises_auth_error(client: HomebearsClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/circles", status=401, json={"error": {"code": "unauthenticated", "message": "Unauthenticated."}}
    )

    with pytest.raises(HomebearsAuthError):
        await client.get_circles()


async def test_missing_scope_names_the_scope(client: HomebearsClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{CIRCLE_URL}/households",
        status=403,
        json={
            "error": {
                "code": "insufficient_scope",
                "message": "This API key lacks the households:read scope.",
                "details": {"required_scope": "households:read"},
            }
        },
    )

    with pytest.raises(HomebearsScopeError) as raised:
        await client.get_households(CIRCLE_ID)

    assert raised.value.required_scope == "households:read"


async def test_validation_error_carries_the_message(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{LIST_URL}/items",
        status=422,
        json={"error": {"code": "validation_failed", "message": "The name field is required."}},
    )

    with pytest.raises(HomebearsApiError, match=r"The name field is required\."):
        await client.add_item(CIRCLE_ID, LIST_ID, "")


@pytest.mark.parametrize("failure", [ClientError(), TimeoutError()])
async def test_network_failure_raises_connection_error(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker, failure: Exception
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", exc=failure)

    with pytest.raises(HomebearsConnectionError):
        await client.get_circles()


async def test_server_error_raises_connection_error(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", status=503, text="maintenance")

    with pytest.raises(HomebearsConnectionError):
        await client.get_circles()


async def test_success_without_a_data_list_is_an_api_error(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", json={"message": "Welcome to some other API"})

    with pytest.raises(HomebearsApiError):
        await client.get_circles()


async def test_error_body_with_null_fields_still_raises_api_error(
    client: HomebearsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/circles", status=403, json={"error": None})

    with pytest.raises(HomebearsApiError):
        await client.get_circles()


async def test_empty_success_body_is_fine(client: HomebearsClient, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{LIST_URL}/items/i1/check", status=200, text="")

    await client.set_item_checked(CIRCLE_ID, LIST_ID, "i1", True)
