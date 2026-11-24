"""Polls the selected shopping lists and households of one circle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, tzinfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import HomebearsApiError, HomebearsAuthError, HomebearsClient, HomebearsError, Json
from .const import CONF_CIRCLE_ID, CONF_HOUSEHOLDS, CONF_SHOPPING_LISTS, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Short, so a run of quick to-do edits shows up at once instead of after the default 10 s cooldown.
REFRESH_COOLDOWN = 1.0

type HomebearsConfigEntry = ConfigEntry[HomebearsCoordinator]


@dataclass(frozen=True, slots=True)
class ShoppingList:
    id: str
    name: str
    open_count: int
    checked_count: int
    updated_at: str | None
    items: list[Json]


@dataclass(frozen=True, slots=True)
class Household:
    id: str
    name: str
    timezone: tzinfo
    open_today: list[Json]

    @property
    def today(self) -> date:
        return dt_util.now(self.timezone).date()


@dataclass(frozen=True, slots=True)
class HomebearsData:
    shopping_lists: dict[str, ShoppingList]
    households: dict[str, Household]


class HomebearsCoordinator(DataUpdateCoordinator[HomebearsData]):
    """Fetches everything the entities of one config entry show.

    A list or household gone from the API, or one the key may no longer read, drops out on its own; only an
    invalid key or an unreachable API fails the whole update.
    """

    config_entry: HomebearsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HomebearsConfigEntry, client: HomebearsClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=REFRESH_COOLDOWN, immediate=True),
        )
        self.client = client
        self.circle_id: str = entry.data[CONF_CIRCLE_ID]

    async def _async_update_data(self) -> HomebearsData:
        options = self.config_entry.options
        try:
            shopping_lists, households = await asyncio.gather(
                self._fetch_shopping_lists(options.get(CONF_SHOPPING_LISTS, [])),
                self._fetch_households(options.get(CONF_HOUSEHOLDS, [])),
            )
        except HomebearsAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HomebearsError as err:
            raise UpdateFailed(str(err)) from err
        return HomebearsData(shopping_lists, households)

    async def _fetch_shopping_lists(self, selected: list[str]) -> dict[str, ShoppingList]:
        rows = await self._selected_rows(self.client.get_shopping_lists, selected, "shopping lists")
        items = await asyncio.gather(*(self._readable(self.client.get_items(self.circle_id, r["id"])) for r in rows))
        return {
            row["id"]: ShoppingList(
                id=row["id"],
                name=row.get("name") or "",
                open_count=row.get("open_count") or 0,
                checked_count=row.get("checked_count") or 0,
                updated_at=row.get("updated_at"),
                items=row_items,
            )
            for row, row_items in zip(rows, items, strict=True)
            if row_items is not None
        }

    async def _fetch_households(self, selected: list[str]) -> dict[str, Household]:
        rows = await self._selected_rows(self.client.get_households, selected, "households")
        households = [
            Household(row["id"], row.get("name") or "", await self._timezone(row.get("timezone")), []) for row in rows
        ]
        occurrences = await asyncio.gather(
            *(self._readable(self.client.get_open_occurrences(self.circle_id, h.id, h.today)) for h in households)
        )
        return {
            h.id: Household(h.id, h.name, h.timezone, open_today)
            for h, open_today in zip(households, occurrences, strict=True)
            if open_today is not None
        }

    async def _selected_rows(
        self, fetch: Callable[[str], Awaitable[list[Json]]], selected: list[str], what: str
    ) -> list[Json]:
        if not selected:
            return []
        rows = await self._readable(fetch(self.circle_id))
        if rows is None:
            _LOGGER.warning("The API key may no longer read the %s of circle %s", what, self.circle_id)
            return []
        return [row for row in rows if row.get("id") in selected]

    @staticmethod
    async def _readable(request: Awaitable[list[Json]]) -> list[Json] | None:
        """The rows, or None when the API refuses this one resource (missing scope, deleted meanwhile)."""
        try:
            return await request
        except HomebearsAuthError:
            raise
        except HomebearsApiError as err:
            _LOGGER.debug("Skipping a resource Homebears refused: %s", err)
            return None

    @staticmethod
    async def _timezone(name: str | None) -> tzinfo:
        # The household's own day decides what "today" is; Home Assistant's zone only when it has none we know.
        try:
            zone = await dt_util.async_get_time_zone(name) if name else None
        except ValueError:  # a malformed key such as an absolute path, not just an unknown zone
            zone = None
        return zone or dt_util.get_default_time_zone()
