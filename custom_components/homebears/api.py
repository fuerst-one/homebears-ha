"""Small async client for the Homebears REST API v1."""

from __future__ import annotations

from datetime import date
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

PER_PAGE = 100
TIMEOUT = ClientTimeout(total=20)

type Json = dict[str, Any]


class HomebearsError(Exception):
    """Base error of the Homebears client."""


class HomebearsConnectionError(HomebearsError):
    """Homebears could not be reached or failed on its side (5xx); worth retrying."""


class HomebearsAuthError(HomebearsError):
    """The key is missing, wrong, expired or revoked."""


class HomebearsApiError(HomebearsError):
    """Homebears refused the request (4xx); `message` is the API's own explanation."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class HomebearsScopeError(HomebearsApiError):
    """The key lacks the scope this request needs."""

    def __init__(self, message: str, required_scope: str | None) -> None:
        super().__init__(403, "insufficient_scope", message)
        self.required_scope = required_scope


class HomebearsClient:
    """Talks to one Homebears API base URL with one personal API key."""

    def __init__(self, session: ClientSession, base_url: str, api_key: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    async def get_circles(self) -> list[Json]:
        return await self._get_all("/circles")

    async def get_households(self, circle_id: str) -> list[Json]:
        return await self._get_all(f"/circles/{circle_id}/households")

    async def get_shopping_lists(self, circle_id: str) -> list[Json]:
        return await self._get_all(f"/circles/{circle_id}/shopping-lists")

    async def get_items(self, circle_id: str, list_id: str) -> list[Json]:
        return await self._get_all(self._items(circle_id, list_id))

    async def add_item(
        self, circle_id: str, list_id: str, name: str, quantity: str | None = None, op_id: str | None = None
    ) -> Json:
        body = {"name": name, "quantity": quantity, "op_id": op_id}
        return await self._request(
            "POST", self._items(circle_id, list_id), {k: v for k, v in body.items() if v is not None}
        )

    async def update_item(self, circle_id: str, list_id: str, item_id: str, fields: Json) -> Json:
        return await self._request("PATCH", f"{self._items(circle_id, list_id)}/{item_id}", fields)

    async def set_item_checked(self, circle_id: str, list_id: str, item_id: str, checked: bool) -> Json:
        action = "check" if checked else "uncheck"
        return await self._request("POST", f"{self._items(circle_id, list_id)}/{item_id}/{action}")

    async def delete_item(self, circle_id: str, list_id: str, item_id: str) -> None:
        await self._request("DELETE", f"{self._items(circle_id, list_id)}/{item_id}")

    async def get_chores(self, circle_id: str, household_id: str) -> list[Json]:
        return await self._get_all(f"{self._household(circle_id, household_id)}/cleaning-tasks")

    async def get_open_occurrences(self, circle_id: str, household_id: str, day: date) -> list[Json]:
        return await self._get_all(
            f"{self._household(circle_id, household_id)}/occurrences",
            {"status": "open", "from": day.isoformat(), "to": day.isoformat()},
        )

    async def complete_occurrence(
        self, circle_id: str, household_id: str, occurrence_id: str, credited_user_id: str | None = None
    ) -> Json:
        return await self._request(
            "POST",
            f"{self._household(circle_id, household_id)}/occurrences/{occurrence_id}/complete",
            _credit(credited_user_id),
        )

    async def complete_on_demand_chore(
        self, circle_id: str, household_id: str, chore_id: str, credited_user_id: str | None = None
    ) -> Json:
        return await self._request(
            "POST",
            f"{self._household(circle_id, household_id)}/cleaning-tasks/{chore_id}/complete",
            _credit(credited_user_id),
        )

    @staticmethod
    def _items(circle_id: str, list_id: str) -> str:
        return f"/circles/{circle_id}/shopping-lists/{list_id}/items"

    @staticmethod
    def _household(circle_id: str, household_id: str) -> str:
        return f"/circles/{circle_id}/households/{household_id}"

    async def _get_all(self, path: str, params: dict[str, str] | None = None) -> list[Json]:
        rows: list[Json] = []
        page = 1
        while True:
            body = await self._request(
                "GET", path, params={**(params or {}), "page": str(page), "per_page": str(PER_PAGE)}
            )
            data = body.get("data")
            if not isinstance(data, list):
                raise HomebearsApiError(200, "unexpected_response", f"{path} did not answer with a list")
            rows.extend(data)
            if page >= ((body.get("meta") or {}).get("last_page") or page):
                return rows
            page += 1

    async def _request(
        self, method: str, path: str, json: Json | None = None, params: dict[str, str] | None = None
    ) -> Json:
        try:
            async with self._session.request(
                method, self._base_url + path, headers=self._headers, json=json, params=params, timeout=TIMEOUT
            ) as response:
                return await _read(response)
        except (ClientError, TimeoutError) as err:
            raise HomebearsConnectionError(str(err) or type(err).__name__) from err


async def _read(response: ClientResponse) -> Json:
    if response.status == 204:
        return {}
    if response.status >= 500:
        raise HomebearsConnectionError(f"Homebears answered {response.status}")
    try:
        body = await response.json(content_type=None)
    except ValueError:
        body = None
    if response.status < 400:
        return body if isinstance(body, dict) else {}

    error = (body.get("error") if isinstance(body, dict) else None) or {}
    code = error.get("code") or ""
    message = error.get("message") or f"HTTP {response.status}"
    if response.status == 401:
        raise HomebearsAuthError(message)
    if code == "insufficient_scope":
        raise HomebearsScopeError(message, (error.get("details") or {}).get("required_scope"))
    raise HomebearsApiError(response.status, code, message)


def _credit(credited_user_id: str | None) -> Json:
    return {"credited_user_id": credited_user_id} if credited_user_id else {}
