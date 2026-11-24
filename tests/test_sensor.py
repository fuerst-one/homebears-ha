"""Tests for the Homebears sensors."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import HOUSEHOLD_URL, setup_integration


async def test_open_items_sensor(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    state = hass.states.get("sensor.groceries_open_items")

    assert state.state == "2"
    assert state.attributes["name"] == "Groceries"
    assert state.attributes["checked_count"] == 1
    assert state.attributes["updated_at"] == "2026-11-24T08:00:00.000000Z"
    assert state.attributes["unit_of_measurement"] == "items"


async def test_only_selected_lists_get_entities(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.hardware_open_items") is None


async def test_chores_open_today_sensor(hass: HomeAssistant, mock_api, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)

    state = hass.states.get("sensor.home_chores_open_today")

    assert state.state == "2"
    assert state.attributes["chores"] == [
        {"occurrence_id": "o1", "chore_id": "t1", "name": "Empty the dishwasher", "assignee": "Anna"},
        {"occurrence_id": "o2", "chore_id": "t2", "name": "Take out the bins", "assignee": "Anna"},
    ]
    assert state.attributes["names"] == "Empty the dishwasher, Take out the bins"


async def test_today_is_the_households_date(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_api,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-24T23:30:00+00:00")

    await setup_integration(hass, config_entry)

    occurrence_calls = [url for method, url, _, _ in aioclient_mock.mock_calls if str(url).startswith(HOUSEHOLD_URL)]
    assert occurrence_calls[0].query["from"] == "2026-11-25"
    assert occurrence_calls[0].query["to"] == "2026-11-25"
