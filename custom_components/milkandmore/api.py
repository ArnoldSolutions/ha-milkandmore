"""Client for the Milk & More website.

Milk & More has no public API. This client logs in to the website the
same way a browser does and reads the "My Deliveries" weekly fragment
(/my-account/my-orders-new/weekly-order?weekStart=YYYY-MM-DD), which is
HTML. If Milk & More change their site, the parser below is the part
that will need updating.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import aiohttp
from bs4 import BeautifulSoup

from .const import BASE_URL, LOGIN_PAGE, LOGIN_POST, USER_AGENT, WEEKLY_ORDER

_LOGGER = logging.getLogger(__name__)

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}
_PRICE_RE = re.compile(r"£\s*([\d,]+(?:\.\d{1,2})?)")
_QTY_RE = re.compile(r"(\d+)")
_DAY_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)")


class MilkAndMoreError(Exception):
    """Generic error talking to Milk & More."""


class MilkAndMoreAuthError(MilkAndMoreError):
    """Login failed or the session could not be re-established."""


@dataclass
class DeliveryItem:
    """One product on a delivery day."""

    name: str
    quantity: int
    unit_price: float | None
    subtotal: float | None
    frequency: str | None  # e.g. "Every week"; None for one-off items
    section: str | None  # e.g. "Regular items", "One-off items"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "subtotal": self.subtotal,
            "frequency": self.frequency,
            "section": self.section,
        }


@dataclass
class DeliveryDay:
    """One delivery day as shown on the website."""

    date: date
    items: list[DeliveryItem] = field(default_factory=list)
    total: float | None = None
    status: str | None = None  # e.g. "Complete" once delivered
    editable: bool = False  # site still offers Edit/Skip

    @property
    def has_items(self) -> bool:
        return bool(self.items)

    @property
    def is_complete(self) -> bool:
        return (self.status or "").strip().lower() == "complete"

    def summary(self) -> str:
        return ", ".join(f"{i.quantity}× {i.name}" for i in self.items)


def _price(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(text)
    return float(m.group(1).replace(",", "")) if m else None


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_heading_date(heading: str, week_start: date) -> date | None:
    """Turn 'Monday 19th October' into a date inside the given week."""
    m = _DAY_RE.search(heading)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    for year in (week_start.year, week_start.year + 1, week_start.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if week_start <= candidate <= week_start + timedelta(days=6):
            return candidate
    return None


def _labelled_value(card, label: str) -> str | None:
    """Find the value span that follows a label span such as 'Quantity'."""
    for lab in card.select(".m-productCard__detailsPrice .a-text.-sm"):
        if _clean(lab.get_text()).lower() == label.lower():
            row = lab.parent
            values = [
                s for s in row.select(".a-text.-bold") if s is not lab
            ]
            if values:
                return _clean(values[0].get_text())
    return None


def parse_weekly_order(html: str, week_start: date) -> list[DeliveryDay]:
    """Parse the weekly-order HTML fragment into delivery days."""
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select(".js-delivery-day-container")
    if not containers:
        raise MilkAndMoreError(
            "No delivery days found in the weekly order page "
            "(the website layout may have changed)"
        )

    days: list[DeliveryDay] = []
    for c in containers:
        # Date: prefer the data attribute, fall back to the heading text.
        day_date: date | None = None
        attr = c.select_one("[data-delivery-date]")
        if attr is not None:
            try:
                day_date = date.fromisoformat(attr["data-delivery-date"][:10])
            except ValueError:
                day_date = None
        heading_el = c.select_one(".a-text.-lg")
        if day_date is None and heading_el is not None:
            day_date = _parse_heading_date(_clean(heading_el.get_text()), week_start)
        if day_date is None:
            _LOGGER.debug("Skipping a delivery day with no readable date")
            continue

        # Day-level status tag sits next to the heading (e.g. "Complete").
        status = None
        if heading_el is not None and heading_el.parent is not None:
            tag = heading_el.parent.find(
                lambda t: t.name and "a-tag" in (t.get("class") or [])
            )
            if tag is not None:
                status = _clean(tag.get_text())

        # Items, remembering which section heading ("Regular items" etc.) they sit under.
        items: list[DeliveryItem] = []
        section = None
        for el in c.find_all(True):
            classes = el.get("class") or []
            if "a-text" in classes and "-semibold" in classes and "-md" in classes:
                section = _clean(el.get_text()) or section
            if "m-productCard" in classes and "-basket" in classes:
                name_el = el.select_one(".m-productCard__detailsName a") or el.select_one(
                    ".m-productCard__detailsName"
                )
                name = _clean(name_el.get_text()) if name_el else "Unknown item"
                freq_el = el.select_one(".m-productCard__detailsName .a-tag")
                qty_text = _labelled_value(el, "Quantity") or ""
                qty_m = _QTY_RE.search(qty_text)
                sub_el = el.select_one("[data-entry-price]")
                items.append(
                    DeliveryItem(
                        name=name,
                        quantity=int(qty_m.group(1)) if qty_m else 1,
                        unit_price=_price(_labelled_value(el, "Unit Price")),
                        subtotal=_price(sub_el.get_text() if sub_el else _labelled_value(el, "Sub-Total")),
                        frequency=_clean(freq_el.get_text()) if freq_el else None,
                        section=section,
                    )
                )

        # Totals table: the row headed "Total".
        total = None
        for row in c.select(".t-basket__totals tr"):
            th = row.find("th")
            if th is not None and _clean(th.get_text()).lower().startswith("total"):
                total = _price(row.find("td").get_text() if row.find("td") else None)
        if total is None and items:
            subs = [i.subtotal for i in items if i.subtotal is not None]
            total = round(sum(subs), 2) if subs else None

        editable = bool(
            c.select_one(
                ".js-skip-delivery-modal, .js-edit-upcoming-delivery-item-popup, "
                ".js-remove-item, [data-delivery-date]"
            )
        )

        days.append(
            DeliveryDay(
                date=day_date, items=items, total=total, status=status, editable=editable
            )
        )
    return days


class MilkAndMoreClient:
    """Logs in to milkandmore.co.uk and reads upcoming deliveries."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._logged_in = False

    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"}

    async def login(self) -> None:
        """Log in with the website form. Raises MilkAndMoreAuthError on bad credentials."""
        try:
            async with self._session.get(
                BASE_URL + LOGIN_PAGE, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                page = await resp.text()
        except aiohttp.ClientError as err:
            raise MilkAndMoreError(f"Could not load login page: {err}") from err

        soup = BeautifulSoup(page, "html.parser")
        form = soup.find(
            "form", action=lambda a: bool(a) and "j_spring_security_check" in a
        )
        token_el = (form or soup).find("input", attrs={"name": "CSRFToken"})
        if token_el is None or not token_el.get("value"):
            raise MilkAndMoreError("Login form not found (the website may have changed)")

        data = {
            "j_username": self._email,
            "j_password": self._password,
            "CSRFToken": token_el["value"],
        }
        try:
            async with self._session.post(
                BASE_URL + LOGIN_POST,
                data=data,
                headers={**self._headers, "Referer": BASE_URL + LOGIN_PAGE},
                allow_redirects=True,
            ) as resp:
                final_url = str(resp.url)
                await resp.read()
        except aiohttp.ClientError as err:
            raise MilkAndMoreError(f"Login request failed: {err}") from err

        if "/login" in final_url:
            self._logged_in = False
            raise MilkAndMoreAuthError("Milk & More rejected the email or password")
        self._logged_in = True
        _LOGGER.debug("Logged in to Milk & More")

    async def _get_week_html(self, week_start: date) -> str | None:
        """Return the fragment HTML, or None if the session has expired."""
        url = f"{BASE_URL}{WEEKLY_ORDER}?weekStart={week_start.isoformat()}"
        try:
            async with self._session.get(
                url,
                headers={**self._headers, "X-Requested-With": "XMLHttpRequest"},
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308, 401, 403):
                    return None
                resp.raise_for_status()
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise MilkAndMoreError(f"Could not load deliveries: {err}") from err
        if "j_spring_security_check" in text:
            return None  # we were handed the login page
        return text

    async def async_get_week(self, week_start: date) -> list[DeliveryDay]:
        """Fetch and parse one week (week_start must be a Monday)."""
        if not self._logged_in:
            await self.login()
        html = await self._get_week_html(week_start)
        if html is None:
            _LOGGER.debug("Milk & More session expired, logging in again")
            self._logged_in = False
            await self.login()
            html = await self._get_week_html(week_start)
            if html is None:
                raise MilkAndMoreAuthError("Could not stay logged in to Milk & More")
        return parse_weekly_order(html, week_start)
