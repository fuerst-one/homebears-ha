# Homebears for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/fuerst-one/homebears-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/fuerst-one/homebears-ha/actions/workflows/validate.yml)

Brings your [Homebears](https://homebears.app) shopping lists and chores into Home Assistant:

- every shopping list you pick becomes a **to-do list** (add, tick off, rename, remove items; works with the
  to-do card, Assist and automations) and an **open items** sensor,
- every household you pick gets a **chores open today** sensor,
- two actions, `homebears.add_shopping_item` and `homebears.complete_chore`, for buttons, voice and automations
  (tick off the laundry when the washer finishes, the vacuuming when the robot docks).

You never have to look up an id: setup lists your circles, lists and households from the API.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/fuerst-one/homebears-ha`, type **Integration**.
2. Search for **Homebears**, download it and restart Home Assistant.

### Manually

Copy `custom_components/homebears` into your Home Assistant `config/custom_components/` folder and restart.

## Setup

1. In the Homebears app go to **Settings → API keys** ([my.homebears.app/settings/api-keys](https://my.homebears.app/settings/api-keys))
   and create a key named "Home Assistant". Restrict it to your circle and give it the scopes you need:

   | For                                                      | Scope             |
   | -------------------------------------------------------- | ----------------- |
   | Shopping lists: to-do list, sensor, `add_shopping_item` | `shopping:write`  |
   | Shopping lists, read only (sensor and to-do list view)   | `shopping:read`   |
   | Chores sensor and `complete_chore`                       | `cleaning:write`  |
   | Chores sensor only                                       | `cleaning:read`   |
   | Listing your households during setup                     | `households:read` |

   Everything: **`shopping:write`, `cleaning:write`, `households:read`** (a write scope includes its read scope).
   The key (`hb_…`) is shown only once.

2. **Settings → Devices & services → Add integration → Homebears.** Paste the key (leave the API address as is
   unless you run your own server), pick the circle if the key reaches several, then tick the shopping lists and
   households to show. Each circle is its own entry; change the selection later under **Configure**.

If the key is revoked or expires, Home Assistant shows a **re-authenticate** prompt on the entry; paste a new key there.

## Entities

Each shopping list and each household is a device.

| Entity                                | State                         | Attributes                                                                      |
| ------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------- |
| `todo.<list>`                         | Open items                    | Items: name as summary, quantity as description, ticked items as completed      |
| `sensor.<list>_open_items`            | Open items                    | `name`, `checked_count`, `updated_at`                                           |
| `sensor.<household>_chores_open_today` | Chores due today, not done or skipped | `chores` (`occurrence_id`, `chore_id`, `name`, `assignee`), `names` (comma-separated) |

"Today" is the household's own date (its timezone in Homebears), not Home Assistant's.

## Actions

### `homebears.add_shopping_item`

| Field       | Required | Description                                                                                                        |
| ----------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| `entity_id` | yes      | A Homebears to-do list, e.g. `todo.groceries`                                                                      |
| `item`      | yes      | What to buy                                                                                                        |
| `quantity`  | no       | Free text: `2`, `500 g`                                                                                            |
| `op_id`     | no       | Makes the call safe to repeat: Homebears applies the same id once within 24 hours (`[A-Za-z0-9._:-]`, at most 64) |

`todo.add_item` works too (its `description` becomes the quantity); use this action when you want `op_id`.

```yaml
# A button that adds milk; a double press within the same minute adds it once.
- action: homebears.add_shopping_item
  data:
    entity_id: todo.groceries
    item: Milk
    op_id: "ha-milk-{{ now().strftime('%Y%m%d%H%M') }}"
```

### `homebears.complete_chore`

| Field              | Required                  | Description                                                                                          |
| ------------------ | ------------------------- | ---------------------------------------------------------------------------------------------------- |
| `entity_id`        | if several households     | The household's `sensor.<household>_chores_open_today`                                               |
| `chore`            | this or `occurrence_id`   | The chore's name (any case) or id                                                                    |
| `occurrence_id`    | this or `chore`           | One occurrence, e.g. from the sensor's `chores` attribute                                            |
| `credited_user_id` | no                        | The member who gets the points (default: the key's owner)                                            |

A **scheduled** chore completes today's open occurrence and fails with a clear message if there is none (already
done, skipped or not due today). An **on-demand** chore (no schedule) is logged as done now.

```yaml
# Tick off today's vacuuming when the robot docks.
automation:
  - alias: "Homebears: vacuuming done"
    triggers:
      - trigger: state
        entity_id: vacuum.robot
        from: [cleaning, returning]
        to: docked
    actions:
      - action: homebears.complete_chore
        continue_on_error: true # nothing to do when it is not due today
        data:
          chore: Vacuum the living room

  - alias: "Homebears: laundry done"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.washing_machine_power
        below: 5
        for: "00:02:00"
    actions:
      - action: homebears.complete_chore
        data:
          chore: Hang up the laundry
```

## How it talks to Homebears

- **Polling**, once a minute (Homebears has no push for integrations yet). One poll costs one request for the lists,
  one per selected list, one for the households and one per selected household, well inside the API limit of 120
  requests a minute per key. After every change Home Assistant makes, it polls again right away.
- If the key loses a scope or a list is deleted in the app, only the affected entities become unavailable; the rest
  keeps working. Lists and households you untick under **Configure** are removed with their devices.
- Changes from the app show up in Home Assistant within about a minute; changes from Home Assistant show up in the
  app at once.
- Everything goes through the public [Homebears REST API](https://api.homebears.app/api/v1/openapi.json) as the
  key's owner: completed chores give that person the points, added items are theirs.

## Without the integration

[`examples/homebears.yaml`](examples/homebears.yaml) is a plain YAML package (`rest_command`, `rest` sensors, a
script and automations) that does the same with Home Assistant's built-in integrations, if you prefer not to
install anything. You fill in the ids yourself there.

## Development

```sh
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

CI runs the tests, `hassfest` and the HACS validation on every push. To release, bump `version` in
`custom_components/homebears/manifest.json` and publish a GitHub release tagged `v<version>`.

## License

MIT
