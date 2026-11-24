"""A Homebears shopping list as a Home Assistant to-do list; the item's quantity is its description."""

from __future__ import annotations

from typing import Any

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import HomebearsApiError
from .const import DOMAIN
from .coordinator import HomebearsConfigEntry, HomebearsCoordinator, ShoppingList
from .entity import ShoppingListEntity
from .errors import raise_for_homebears

PARALLEL_UPDATES = 0

NOT_FOUND = 404


async def async_setup_entry(
    hass: HomeAssistant, entry: HomebearsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        HomebearsTodoList(entry.runtime_data, shopping_list)
        for shopping_list in entry.runtime_data.data.shopping_lists.values()
    )


class HomebearsTodoList(ShoppingListEntity, TodoListEntity):
    _attr_name = None
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator: HomebearsCoordinator, shopping_list: ShoppingList) -> None:
        super().__init__(coordinator, shopping_list, None)

    @property
    def todo_items(self) -> list[TodoItem] | None:
        if not self.available:
            return None
        return [_to_todo_item(item) for item in self.shopping_list.items]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        client, circle_id = self.coordinator.client, self.coordinator.circle_id
        try:
            async with raise_for_homebears():
                await client.add_item(circle_id, self.list_id, item.summary or "", quantity=item.description or None)
        finally:
            await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = next((i for i in self.todo_items or [] if i.uid == item.uid), None)
        if current is None or item.uid is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={"item": item.summary or item.uid or ""},
            )
        fields: dict[str, Any] = {}
        if item.summary != current.summary:
            fields["name"] = item.summary
        if item.description != current.description:
            fields["quantity"] = item.description or None
        client, circle_id = self.coordinator.client, self.coordinator.circle_id
        try:
            async with raise_for_homebears():
                if fields:
                    await client.update_item(circle_id, self.list_id, item.uid, fields)
                if item.status != current.status:
                    checked = item.status == TodoItemStatus.COMPLETED
                    await client.set_item_checked(circle_id, self.list_id, item.uid, checked)
        finally:
            await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        client, circle_id = self.coordinator.client, self.coordinator.circle_id
        try:
            async with raise_for_homebears():
                for uid in uids:
                    try:
                        await client.delete_item(circle_id, self.list_id, uid)
                    except HomebearsApiError as err:
                        # Someone removed it in the app since the last poll: what was asked for is done.
                        if err.status != NOT_FOUND:
                            raise
        finally:
            await self.coordinator.async_request_refresh()


def _to_todo_item(item: dict[str, Any]) -> TodoItem:
    return TodoItem(
        uid=item["id"],
        summary=item.get("name") or "",
        status=TodoItemStatus.COMPLETED if item.get("checked_at") else TodoItemStatus.NEEDS_ACTION,
        description=item.get("quantity") or None,
    )
