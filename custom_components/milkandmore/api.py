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

from .const import BASE_URL, LOGIN_PAGE, LOGIN_POST, SKIP_PAGE, USER_AGENT, WEEKLY_ORDER

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

    @property
    def is_skipped(self) -> bool:
        return (self.status or "").strip().lower() == "skipped"

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


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_skip_page(html: str) -> tuple[set[str], str]:
    """Skipped dates and CSRF token from /my-account/skip-delivery."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", action=lambda a: bool(a) and "skip-delivery" in a)
    if form is None:
        raise MilkAndMoreError("Skip Deliveries form not found (the website may have changed)")
    token_el = form.find("input", attrs={"name": "CSRFToken"})
    if token_el is None or not token_el.get("value"):
        raise MilkAndMoreError("Skip Deliveries form has no CSRF token")
    data_el = soup.select_one(".js-calendar-data")
    if data_el is None:
        raise MilkAndMoreError("Skip Deliveries calendar data not found")
    raw = data_el.get("value") or ""
    skipped = {d.strip() for d in raw.split(",") if _ISO_RE.match(d.strip())}
    return skipped, token_el["value"]


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

    async def _get(self, path: str) -> str | None:
        """GET a page; None if the session has expired (redirect or login page)."""
        try:
            async with self._session.get(
                BASE_URL + path,
                headers={**self._headers, "X-Requested-With": "XMLHttpRequest"},
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308, 401, 403):
                    return None
                resp.raise_for_status()
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise MilkAndMoreError(f"Could not load {path}: {err}") from err
        if "j_spring_security_check" in text:
            return None  # we were handed the login page
        return text

    async def _authed_get(self, path: str) -> str:
        """GET a page, logging in (again) if needed."""
        if not self._logged_in:
            await self.login()
        html = await self._get(path)
        if html is None:
            _LOGGER.debug("Milk & More session expired, logging in again")
            self._logged_in = False
            await self.login()
            html = await self._get(path)
            if html is None:
                raise MilkAndMoreAuthError("Could not stay logged in to Milk & More")
        return html

    async def async_get_week(self, week_start: date) -> list[DeliveryDay]:
        """Fetch and parse one week (week_start must be a Monday)."""
        html = await self._authed_get(f"{WEEKLY_ORDER}?weekStart={week_start.isoformat()}")
        return parse_weekly_order(html, week_start)

    # ── Skip / un-skip (the website's "Skip Deliveries" calendar) ──

    async def _get_skip_page(self) -> tuple[set[str], str]:
        """Return (currently skipped ISO dates, CSRF token) from the skip page."""
        html = await self._authed_get(SKIP_PAGE)
        return parse_skip_page(html)

    async def async_get_skipped(self) -> set[str]:
        """ISO dates the website currently has marked as skipped."""
        skipped, _token = await self._get_skip_page()
        return skipped

    async def _toggle(self, dates: list[str], token: str) -> None:
        """POST the website's skip/un-skip toggle for the given ISO dates."""
        # The website sends this as multipart form data; do the same.
        try:
            form = aiohttp.FormData(default_to_multipart=True)
        except TypeError:  # older aiohttp
            form = aiohttp.FormData()
        form.add_field("skipDeliveryDates", ",".join(sorted(dates)))
        form.add_field("CSRFToken", token)
        try:
            async with self._session.post(
                BASE_URL + SKIP_PAGE,
                data=form,
                headers={
                    **self._headers,
                    "CSRFToken": token,
                    "Referer": BASE_URL + SKIP_PAGE,
                    "Origin": BASE_URL,
                },
                allow_redirects=False,
            ) as resp:
                if resp.status in (401, 403):
                    raise MilkAndMoreError(f"Milk & More refused the change (HTTP {resp.status})")
                if resp.status >= 400:
                    raise MilkAndMoreError(f"Milk & More returned HTTP {resp.status}")
                await resp.read()
        except aiohttp.ClientError as err:
            raise MilkAndMoreError(f"Could not send the change: {err}") from err

    async def _change(self, dates: list[str], skip: bool) -> dict[str, list[str]]:
        """Skip (or un-skip) the dates that need it, then read back and report."""
        wanted = sorted({d for d in dates if _ISO_RE.match(d)})
        before, token = await self._get_skip_page()
        to_toggle = [d for d in wanted if (d not in before) == skip]
        unchanged = [d for d in wanted if d not in to_toggle]
        if to_toggle:
            await self._toggle(to_toggle, token)
        after = await self.async_get_skipped()
        done = [d for d in to_toggle if (d in after) == skip]
        failed = [d for d in to_toggle if d not in done]
        if failed:
            _LOGGER.warning(
                "Milk & More did not %s %s", "skip" if skip else "restore", ", ".join(failed)
            )
        return {"changed": done, "already": unchanged, "failed": failed, "skipped_now": sorted(after)}

    async def async_skip(self, dates: list[str]) -> dict[str, list[str]]:
        """Skip deliveries on these ISO dates (dates already skipped are left alone)."""
        return await self._change(dates, skip=True)

    async def async_unskip(self, dates: list[str]) -> dict[str, list[str]]:
        """Restore deliveries on these ISO dates (dates not skipped are left alone)."""
        return await self._change(dates, skip=False)
