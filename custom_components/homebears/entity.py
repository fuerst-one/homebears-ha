"""Base entities: one device per shopping list and per household."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .coordinator import HomebearsCoordinator, Household, ShoppingList

APP_URL = "https://my.homebears.app"


class HomebearsEntity(CoordinatorEntity[HomebearsCoordinator]):
    _attr_has_entity_name = True

    def _app_link(self, path: str) -> str | None:
        # Only the hosted service has a known web app; a self-hosted API base gets no link.
        if self.coordinator.config_entry.data[CONF_BASE_URL] != DEFAULT_BASE_URL:
            return None
        return f"{APP_URL}/c/{self.coordinator.circle_id}{path}"


class ShoppingListEntity(HomebearsEntity):
    def __init__(self, coordinator: HomebearsCoordinator, shopping_list: ShoppingList, key: str | None) -> None:
        super().__init__(coordinator)
        self.list_id = shopping_list.id
        self._attr_unique_id = shopping_list.id if key is None else f"{shopping_list.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, shopping_list.id)},
            name=shopping_list.name,
            manufacturer="Homebears",
            model="Shopping list",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=self._app_link(f"/shopping/{shopping_list.id}"),
        )

    @property
    def shopping_list(self) -> ShoppingList:
        return self.coordinator.data.shopping_lists[self.list_id]

    @property
    def available(self) -> bool:
        return super().available and self.list_id in self.coordinator.data.shopping_lists


class HouseholdEntity(HomebearsEntity):
    def __init__(self, coordinator: HomebearsCoordinator, household: Household, key: str) -> None:
        super().__init__(coordinator)
        self.household_id = household.id
        self._attr_unique_id = f"{household.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, household.id)},
            name=household.name,
            manufacturer="Homebears",
            model="Household",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=self._app_link("/cleaning"),
        )

    @property
    def household(self) -> Household:
        return self.coordinator.data.households[self.household_id]

    @property
    def available(self) -> bool:
        return super().available and self.household_id in self.coordinator.data.households
