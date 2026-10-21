"""
Outage of one house from the DTEK Kyiv grids website.

The website answers the address form by ``POST /ua/ajax`` (``method=getHomeNum``)
with every house of a street: the current outage (emergency, planned works,
stabilization), its start and the estimated restoration.

The website is behind Imperva: it may answer any request, ``/ua/ajax`` too, with
a captcha page. The endpoint checks the CSRF pair of the Yii framework: the
``_csrf-dtek-kem`` cookie and the ``X-CSRF-Token`` header. The user takes the pair
once from the browser (Copy as cURL of the request of the address form) after
passing the captcha; the Imperva cookies of that request (``visid_incap_*``,
``incap_ses_*``, ...) are sent too - with them Imperva shows the captcha less often.

After a captcha page the next request is made in CAPTCHA_RETRY; without a
successful answer for STALE the data is stale (the coordinator shows no outage).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from urllib.parse import unquote_plus
from zoneinfo import ZoneInfo

import aiohttp

LOGGER = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

DTEK_KEM_AJAX_URL = "https://www.dtek-kem.com.ua/ua/ajax"
DTEK_KEM_REFERER = "https://www.dtek-kem.com.ua/ua/shutdowns"
CSRF_COOKIE = "_csrf-dtek-kem"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Cookie value: Yii signed string; token: base64url with padding
_COOKIE_RE = re.compile(
    rf"{re.escape(CSRF_COOKIE)}[\"']?\s*(?:=|,)\s*[\"']?([^;\"'\s,)]+)"
)
_TOKEN_RE = re.compile(
    r"x-csrf-token[\"']?\s*(?::|=)\s*[\"']?([A-Za-z0-9_\-+/]+=*)", re.IGNORECASE
)
# The street of the address form request body: data[1][value]=вул.+...
# Imperva cookies in a cookie string (-b / cookie header) or a PowerShell Cookie
_IMPERVA_NAME = r"(?:visid_incap_\d+|incap_ses_\d+_\d+|incap_wrt_\d+|nlbi_\d+|reese84)"
_IMPERVA_PAIR_RE = re.compile(rf"({_IMPERVA_NAME})=([^;\"'\s,)]+)")
_IMPERVA_PS_RE = re.compile(
    rf"Cookie\(\s*\"({_IMPERVA_NAME})\"\s*,\s*\"([^\"]+)\"", re.IGNORECASE
)

# After a captcha page - the next request; without data for STALE - stale
CAPTCHA_RETRY = datetime.timedelta(minutes=30)
STALE = datetime.timedelta(hours=2)
_STREET_RE = re.compile(r"data%5B1%5D%5Bvalue%5D=([^&'\"\s]+)", re.IGNORECASE)


class DtekAddressError(Exception):
    """The website did not answer."""


class DtekAddressAuthError(DtekAddressError):
    """The CSRF pair is not accepted any more: a new one is needed."""


class DtekAddressStreetError(DtekAddressError):
    """The website does not know the street."""


class DtekAddressCaptchaError(DtekAddressError):
    """Imperva answered with a captcha page instead of the data."""


class AddressOutageKind(StrEnum):
    """Kind of the outage of the house."""

    NORMAL = "normal"
    EMERGENCY = "emergency"
    PLANNED = "planned"
    STABILIZATION = "stabilization"
    OTHER = "other"


@dataclass(frozen=True)
class DtekCredentials:
    """CSRF pair of the website and the Imperva cookies of the browser."""

    cookie: str
    token: str
    imperva: dict[str, str] = field(default_factory=dict)

    def cookies(self) -> dict[str, str]:
        """Cookies of a request."""
        return {**self.imperva, CSRF_COOKIE: self.cookie}


@dataclass(frozen=True)
class AddressOutage:
    """Outage of the house; all empty when the house has electricity."""

    kind: AddressOutageKind
    reason: str | None
    start: datetime.datetime | None
    end: datetime.datetime | None
    type: str | None
    groups: tuple[str, ...]


def parse_credentials(text: str) -> tuple[DtekCredentials | None, str | None]:
    """
    Find the CSRF pair and the street in a request copied from the browser.

    Supports Copy as cURL (bash and cmd) and Copy as PowerShell. Returns
    (credentials or None, street or None).
    """
    # cmd escapes special characters with ^
    text = text.replace("^", "")
    cookie = _COOKIE_RE.search(text)
    token = _TOKEN_RE.search(text)
    street_match = _STREET_RE.search(text)
    street = None
    if street_match:
        street = unquote_plus(street_match.group(1)).strip() or None
    if not cookie or not token:
        return None, street
    imperva = dict(_IMPERVA_PAIR_RE.findall(text))
    imperva.update(_IMPERVA_PS_RE.findall(text))
    return DtekCredentials(cookie.group(1), token.group(1), imperva), street


def _parse_datetime(value: str | None) -> datetime.datetime | None:
    """'05:31 14.10.2026' (Kyiv time) -> aware datetime."""
    if not value:
        return None
    try:
        naive = datetime.datetime.strptime(value.strip(), "%H:%M %d.%m.%Y")  # noqa: DTZ007
    except ValueError:
        LOGGER.warning("Failed to parse DTEK date: %s", value)
        return None
    return naive.replace(tzinfo=KYIV_TZ)


def _kind(reason: str) -> AddressOutageKind:
    """Kind of the outage by its reason text."""
    text = reason.lower()
    if "авар" in text or "екстр" in text:
        return AddressOutageKind.EMERGENCY
    if "стабіл" in text:
        return AddressOutageKind.STABILIZATION
    if "план" in text:
        return AddressOutageKind.PLANNED
    return AddressOutageKind.OTHER


def parse_house(house: dict) -> AddressOutage:
    """Outage of the house from its item of the website answer."""
    reason = (house.get("sub_type") or "").strip()
    start = _parse_datetime(house.get("start_date"))
    end = _parse_datetime(house.get("end_date"))
    outage_type = house.get("type") or None
    groups = tuple(
        group.removeprefix("GPV") for group in house.get("sub_type_reason") or ()
    )
    if not (reason or start or end or outage_type):
        kind = AddressOutageKind.NORMAL
    else:
        kind = _kind(reason)
    return AddressOutage(kind, reason or None, start, end, outage_type, groups)


def parse_updated_on(value: str | None) -> datetime.datetime | None:
    """``updateTimestamp`` of the answer: '07:18 14.10.2026'."""
    return _parse_datetime(value)


async def fetch_street(
    street: str,
    credentials: DtekCredentials,
    new_cookies: dict[str, str] | None = None,
) -> dict:
    """
    Every house of the street: the answer of the website.

    Imperva cookies set by the answer are added to new_cookies. Raises
    DtekAddressAuthError, DtekAddressCaptchaError, DtekAddressStreetError or
    DtekAddressError.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": credentials.token,
        "Referer": DTEK_KEM_REFERER,
    }
    form = {
        "method": "getHomeNum",
        "data[1][name]": "street",
        "data[1][value]": street,
    }
    try:
        async with (
            aiohttp.ClientSession(cookies=credentials.cookies()) as session,
            session.post(
                DTEK_KEM_AJAX_URL,
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response,
        ):
            text = await response.text()
            status = response.status
            if new_cookies is not None:
                new_cookies.update(
                    {
                        name: morsel.value
                        for name, morsel in response.cookies.items()
                        if re.fullmatch(_IMPERVA_NAME, name)
                    }
                )
    except (aiohttp.ClientError, TimeoutError) as err:
        raise DtekAddressError(str(err)) from err

    # Yii answers a rejected CSRF pair with 400 "Bad Request (#400)"
    if status == 400:  # noqa: PLR2004
        raise DtekAddressAuthError(text[:200])
    if status != 200:  # noqa: PLR2004
        raise DtekAddressError(f"HTTP {status}: {text[:200]}")
    try:
        data = json.loads(text)
    except ValueError as err:
        if "incapsula" in text.lower() or text.lstrip()[:1] == "<":
            raise DtekAddressCaptchaError(text[:200]) from err
        raise DtekAddressError(f"Not JSON: {text[:200]}") from err
    if not data.get("result") or not isinstance(data.get("data"), dict):
        raise DtekAddressStreetError(street)
    return data


class DtekAddressApi:
    """Outage of one house; keeps the last answer when a request fails."""

    def __init__(self, street: str, house: str, credentials: DtekCredentials) -> None:
        """Initialize the source."""
        self.street = street
        self.house = house
        self.credentials = credentials
        self.data: dict | None = None
        self.last_success: datetime.datetime | None = None
        # Captcha: since when (no success between) and when to ask again
        self.captcha_since: datetime.datetime | None = None
        self.retry_after: datetime.datetime | None = None

    async def fetch_data(self, now: datetime.datetime | None = None) -> None:
        """
        Request the street (not before retry_after after a captcha page).

        Raises DtekAddressAuthError when the CSRF pair is not accepted; other
        errors keep the last answer.
        """
        now = now or datetime.datetime.now(tz=KYIV_TZ)
        if self.retry_after is not None and now < self.retry_after:
            return
        new_cookies: dict[str, str] = {}
        try:
            data = await fetch_street(self.street, self.credentials, new_cookies)
        except DtekAddressAuthError:
            raise
        except DtekAddressCaptchaError:
            self.captcha_since = self.captcha_since or now
            self.retry_after = now + CAPTCHA_RETRY
            LOGGER.warning(
                "The DTEK website answered with a captcha page (since %s); "
                "next request at %s",
                self.captcha_since,
                self.retry_after,
            )
            return
        except DtekAddressError as err:
            LOGGER.warning(
                "Failed to fetch the DTEK address %s %s: %s",
                self.street,
                self.house,
                err,
            )
            return
        finally:
            # Imperva refreshes its cookies: keep the new ones (in memory)
            if new_cookies:
                self.credentials = replace(
                    self.credentials,
                    imperva={**self.credentials.imperva, **new_cookies},
                )
        self.data = data
        self.last_success = now
        self.captcha_since = None
        self.retry_after = None

    def is_stale(self, now: datetime.datetime | None = None) -> bool:
        """Return whether the last answer is older than STALE."""
        if self.data is None or self.last_success is None:
            return False
        now = now or datetime.datetime.now(tz=KYIV_TZ)
        return now - self.last_success > STALE

    @property
    def house_data(self) -> dict | None:
        """Item of the house in the last answer."""
        return ((self.data or {}).get("data") or {}).get(self.house)

    def get_outage(self) -> AddressOutage | None:
        """Outage of the house; None without data."""
        house = self.house_data
        return parse_house(house) if house is not None else None

    def get_updated_on(self) -> datetime.datetime | None:
        """When DTEK updated the outages."""
        return parse_updated_on((self.data or {}).get("updateTimestamp"))
