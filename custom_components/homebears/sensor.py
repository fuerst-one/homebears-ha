"""Open-items sensor per shopping list and chores-open-today sensor per household."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHORES_OPEN_TODAY, OPEN_ITEMS
from .coordinator import HomebearsConfigEntry, HomebearsCoordinator, Household, ShoppingList
from .entity import HouseholdEntity, ShoppingListEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomebearsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    data = entry.runtime_data.data
    async_add_entities(
        [
            *(OpenItemsSensor(entry.runtime_data, shopping_list) for shopping_list in data.shopping_lists.values()),
            *(ChoresOpenTodaySensor(entry.runtime_data, household) for household in data.households.values()),
        ]
    )


class OpenItemsSensor(ShoppingListEntity, SensorEntity):
    _attr_translation_key = OPEN_ITEMS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HomebearsCoordinator, shopping_list: ShoppingList) -> None:
        super().__init__(coordinator, shopping_list, OPEN_ITEMS)

    @property
    def native_value(self) -> int:
        return self.shopping_list.open_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "name": self.shopping_list.name,
            "checked_count": self.shopping_list.checked_count,
            "updated_at": self.shopping_list.updated_at,
        }


class ChoresOpenTodaySensor(HouseholdEntity, SensorEntity):
    _attr_translation_key = CHORES_OPEN_TODAY

    def __init__(self, coordinator: HomebearsCoordinator, household: Household) -> None:
        super().__init__(coordinator, household, CHORES_OPEN_TODAY)

    @property
    def native_value(self) -> int:
        return len(self.household.open_today)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        chores = [
            {
                "occurrence_id": occurrence.get("id"),
                "chore_id": occurrence.get("cleaning_task_id"),
                "name": (occurrence.get("task") or {}).get("name") or "",
                "assignee": (occurrence.get("assignee") or {}).get("name"),
            }
            for occurrence in self.household.open_today
        ]
        return {"chores": chores, "names": ", ".join(chore["name"] for chore in chores)}
