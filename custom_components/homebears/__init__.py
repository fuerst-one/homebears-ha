"""The Homebears integration: shopping lists and chores of a Homebears circle."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import HomebearsClient
from .const import CONF_BASE_URL, CONF_HOUSEHOLDS, CONF_SHOPPING_LISTS, DOMAIN
from .coordinator import HomebearsConfigEntry, HomebearsCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomebearsConfigEntry) -> bool:
    client = HomebearsClient(async_get_clientsession(hass), entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])
    coordinator = HomebearsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _remove_stale_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomebearsConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _remove_stale_devices(hass: HomeAssistant, entry: HomebearsConfigEntry) -> None:
    """Drop the devices of deselected lists and households, with their entities.

    Goes by the selection, not by what the last poll returned: a list the API refuses for a moment must not lose
    the names and areas the user gave its entities.
    """
    selected = [*entry.options.get(CONF_SHOPPING_LISTS, []), *entry.options.get(CONF_HOUSEHOLDS, [])]
    current = {(DOMAIN, homebears_id) for homebears_id in selected}
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & current:
            registry.async_remove_device(device.id)
