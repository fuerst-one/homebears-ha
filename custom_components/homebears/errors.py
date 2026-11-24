"""Turns client errors into Home Assistant errors a user can read."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from homeassistant.exceptions import HomeAssistantError

from .api import HomebearsApiError, HomebearsAuthError, HomebearsConnectionError
from .const import DOMAIN


@asynccontextmanager
async def raise_for_homebears() -> AsyncIterator[None]:
    try:
        yield
    except HomebearsAuthError as err:
        # The next poll fails the same way and starts the reauth flow.
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_error") from err
    except HomebearsConnectionError as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="connection_error") from err
    except HomebearsApiError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="api_error", translation_placeholders={"message": err.message}
        ) from err
