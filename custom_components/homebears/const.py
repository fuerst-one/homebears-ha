"""Constants for the Homebears integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "homebears"

DEFAULT_BASE_URL: Final = "https://api.homebears.app/api/v1"

CONF_BASE_URL: Final = "base_url"
CONF_CIRCLE_ID: Final = "circle_id"
CONF_SHOPPING_LISTS: Final = "shopping_lists"
CONF_HOUSEHOLDS: Final = "households"

# One poll costs 1 request for the lists, 1 per selected list, 1 for the households and 1 per selected household;
# the API allows 120 requests a minute per key, shared with whatever else uses the key.
UPDATE_INTERVAL: Final = timedelta(seconds=60)

# Entity keys: translation keys and the suffix of each entity's unique id, which the actions resolve entities by.
OPEN_ITEMS: Final = "open_items"
CHORES_OPEN_TODAY: Final = "chores_open_today"
