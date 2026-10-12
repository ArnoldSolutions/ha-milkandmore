"""Constants for the Milk & More integration."""

from datetime import timedelta

DOMAIN = "milkandmore"

BASE_URL = "https://www.milkandmore.co.uk"
LOGIN_PAGE = "/login"
LOGIN_POST = "/j_spring_security_check"
WEEKLY_ORDER = "/my-account/my-orders-new/weekly-order"

# How often to poll the website.
UPDATE_INTERVAL = timedelta(hours=2)

# Weeks to fetch: this week plus this many weeks ahead.
WEEKS_AHEAD = 2

# Orders can be changed online until 21:00 the day before delivery.
CUTOFF_HOUR = 21
UK_TZ = "Europe/London"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)
