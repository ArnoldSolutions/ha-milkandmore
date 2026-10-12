# Milk & More for Home Assistant (unofficial)

Reads your upcoming [Milk & More](https://www.milkandmore.co.uk) doorstep deliveries into Home Assistant.

> **Unofficial.** Milk & More has no public API. This integration signs in to the website the same way a browser does and reads the *My Deliveries* page. It may break when Milk & More change their site, and automated access may not be allowed by their terms of use. Read-only: it never changes or skips an order.

## What you get

| Entity | Type | What it shows |
|---|---|---|
| `sensor.milk_more_next_delivery` | date | Next day with something on it (attributes: items, total, editable) |
| `sensor.milk_more_next_delivery_items` | text | e.g. `1× Milk & More Fresh Semi Skimmed Milk in Glass, 568ml, 1pt` |
| `sensor.milk_more_next_delivery_total` | £ | Cost of the next delivery |
| `sensor.milk_more_order_cut_off` | timestamp | 21:00 the night before the next changeable delivery day |
| `binary_sensor.milk_more_delivery_tomorrow` | on/off | Something is due tomorrow morning |
| `binary_sensor.milk_more_next_delivery_editable` | on/off | Next delivery can still be changed online |
| `calendar.milk_more_deliveries` | calendar | All-day event on each delivery day, items in the description |

It checks this week and the next two weeks every 2 hours.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repository's URL, category **Integration**.
2. Find **Milk & More** in HACS and download it.
3. Restart Home Assistant.
4. Settings → Devices & services → **Add integration** → **Milk & More**, then sign in with your website email and password.

Credentials are stored in Home Assistant's own config storage, not in this repository or in YAML.

## Install (manual)

Copy `custom_components/milkandmore` into `/config/custom_components/`, restart, then add the integration as above.

## Example: cut-off reminder

```yaml
# ── Milk & More: order cut-off reminder ──
alias: Milk & More cut-off reminder
triggers:
  - trigger: time
    at: sensor.milk_more_order_cut_off
    offset: "-01:00:00"
actions:
  - action: notify.notify
    data:
      title: Milk & More
      message: >
        Orders for {{ state_attr('sensor.milk_more_order_cut_off', 'delivery_date') }}
        lock in an hour. Booked: {{ state_attr('sensor.milk_more_order_cut_off', 'summary') or 'nothing' }}.
mode: single
```

## When it breaks

If entities go unavailable with "website layout may have changed" in the log, the HTML parser in `api.py` (`parse_weekly_order`) needs updating. Turn on debug logging with:

```yaml
logger:
  logs:
    custom_components.milkandmore: debug
```
