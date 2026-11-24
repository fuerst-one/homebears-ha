"""The homebears.add_shopping_item and homebears.complete_chore actions."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import CHORES_OPEN_TODAY, DOMAIN
from .coordinator import HomebearsConfigEntry, HomebearsCoordinator, Household
from .errors import raise_for_homebears

ATTR_ITEM = "item"
ATTR_QUANTITY = "quantity"
ATTR_OP_ID = "op_id"
ATTR_CHORE = "chore"
ATTR_OCCURRENCE_ID = "occurrence_id"
ATTR_CREDITED_USER_ID = "credited_user_id"

CHORES_SENSOR_SUFFIX = f"_{CHORES_OPEN_TODAY}"

ADD_SHOPPING_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ITEM): vol.All(cv.string, vol.Length(min=1, max=255)),
        vol.Optional(ATTR_QUANTITY): vol.All(cv.string, vol.Length(max=255)),
        vol.Optional(ATTR_OP_ID): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9._:-]{1,64}$")),
    }
)

COMPLETE_CHORE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
            vol.Exclusive(ATTR_CHORE, "chore"): cv.string,
            vol.Exclusive(ATTR_OCCURRENCE_ID, "chore"): cv.string,
            vol.Optional(ATTR_CREDITED_USER_ID): cv.string,
        }
    ),
    cv.has_at_least_one_key(ATTR_CHORE, ATTR_OCCURRENCE_ID),
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_shopping_item(call: ServiceCall) -> None:
        coordinator, list_id = _resolve(hass, call.data[ATTR_ENTITY_ID], "todo", "", "not_a_homebears_list")
        async with raise_for_homebears():
            await coordinator.client.add_item(
                coordinator.circle_id,
                list_id,
                call.data[ATTR_ITEM],
                quantity=call.data.get(ATTR_QUANTITY) or None,
                op_id=call.data.get(ATTR_OP_ID) or None,
            )
        await coordinator.async_request_refresh()

    async def complete_chore(call: ServiceCall) -> None:
        coordinator, household = _household_for(hass, call.data.get(ATTR_ENTITY_ID))
        credited = call.data.get(ATTR_CREDITED_USER_ID) or None
        client, circle_id = coordinator.client, coordinator.circle_id
        async with raise_for_homebears():
            if occurrence_id := call.data.get(ATTR_OCCURRENCE_ID):
                await client.complete_occurrence(circle_id, household.id, occurrence_id, credited)
            else:
                await _complete_by_chore(coordinator, household, call.data[ATTR_CHORE], credited)
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "add_shopping_item", add_shopping_item, ADD_SHOPPING_ITEM_SCHEMA)
    hass.services.async_register(DOMAIN, "complete_chore", complete_chore, COMPLETE_CHORE_SCHEMA)


async def _complete_by_chore(
    coordinator: HomebearsCoordinator, household: Household, wanted: str, credited: str | None
) -> None:
    client, circle_id = coordinator.client, coordinator.circle_id
    chores = await client.get_chores(circle_id, household.id)
    by_id = [c for c in chores if c.get("id") == wanted]
    matches = by_id or [c for c in chores if (c.get("name") or "").casefold() == wanted.casefold()]
    if not matches:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="chore_not_found",
            translation_placeholders={"chore": wanted, "household": household.name},
        )
    if on_demand := next((c for c in matches if c.get("on_demand")), None):
        await client.complete_on_demand_chore(circle_id, household.id, on_demand["id"], credited)
        return

    # Fetched fresh rather than from the last poll: someone may have ticked it off in the app since. Several
    # chores may share a name (one per room), so any of them that is open today will do.
    open_today = await client.get_open_occurrences(circle_id, household.id, household.today)
    ids = {c["id"] for c in matches}
    occurrence = next((o for o in open_today if o.get("cleaning_task_id") in ids), None)
    if occurrence is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="chore_not_open_today",
            translation_placeholders={"chore": matches[0].get("name") or wanted, "household": household.name},
        )
    await client.complete_occurrence(circle_id, household.id, occurrence["id"], credited)


def _household_for(hass: HomeAssistant, entity_id: str | None) -> tuple[HomebearsCoordinator, Household]:
    if entity_id is not None:
        coordinator, household_id = _resolve(
            hass, entity_id, "sensor", CHORES_SENSOR_SUFFIX, "not_a_homebears_household"
        )
        return coordinator, coordinator.data.households[household_id]

    candidates = [
        (entry.runtime_data, household)
        for entry in _loaded_entries(hass)
        for household in entry.runtime_data.data.households.values()
    ]
    if len(candidates) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="household_required")
    return candidates[0]


def _resolve(
    hass: HomeAssistant, entity_id: str, domain: str, suffix: str, error_key: str
) -> tuple[HomebearsCoordinator, str]:
    """The coordinator and the Homebears id behind one of this integration's entities."""
    entry = er.async_get(hass).async_get(entity_id)
    loaded = {e.entry_id: e for e in _loaded_entries(hass)}
    if (
        entry is None
        or entry.platform != DOMAIN
        or entry.domain != domain
        or not entry.unique_id.endswith(suffix)
        or entry.config_entry_id not in loaded
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key=error_key, translation_placeholders={"entity_id": entity_id}
        )
    coordinator = loaded[entry.config_entry_id].runtime_data
    homebears_id = entry.unique_id.removesuffix(suffix)
    known = coordinator.data.shopping_lists if domain == "todo" else coordinator.data.households
    if homebears_id not in known:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key=error_key, translation_placeholders={"entity_id": entity_id}
        )
    return coordinator, homebears_id


def _loaded_entries(hass: HomeAssistant) -> list[HomebearsConfigEntry]:
    return [entry for entry in hass.config_entries.async_entries(DOMAIN) if entry.state is ConfigEntryState.LOADED]
