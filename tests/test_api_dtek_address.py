"""Tests for the address outage source (DTEK website)."""

import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.svitlo_kyiv.api.dtek_address import (
    KYIV_TZ,
    AddressOutageKind,
    DtekAddressApi,
    DtekAddressAuthError,
    DtekAddressCaptchaError,
    DtekAddressError,
    DtekAddressStreetError,
    DtekCredentials,
    fetch_street,
    parse_credentials,
    parse_house,
)

COOKIE = "1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2ca%3A2%3A%7Bi"
TOKEN = "AbCdEf_gh-IjKlMnOp_QrStUv-WxYz0123456789_abcdefghijklmnopqrstuv-wxyz01234567_ABCDEFGH=="  # noqa: S105
STREET = "вул. Прикладна"
# data[1][value] of the address form request
BODY = (
    "method=getHomeNum&data%5B0%5D%5Bname%5D=city&data%5B0%5D%5Bvalue%5D="
    "&data%5B1%5D%5Bname%5D=street&data%5B1%5D%5Bvalue%5D="
    "%D0%B2%D1%83%D0%BB.+%D0%9F%D1%80%D0%B8%D0%BA%D0%BB%D0%B0%D0%B4%D0%BD%D0%B0"
)
CURL_BASH = (
    "curl 'https://www.dtek-kem.com.ua/ua/ajax' \\\n"
    "  -H 'accept: application/json, text/javascript, */*; q=0.01' \\\n"
    f"  -b '_language=abc; dtek-kem=xyz; _csrf-dtek-kem={COOKIE}; visid_incap_1=q' \\\n"
    f"  -H 'x-csrf-token: {TOKEN}' \\\n"
    f"  --data-raw '{BODY}'"
)
CURL_CMD = (
    CURL_BASH.replace("'", '^"')
    .replace("%", "^%")
    .replace("&", "^&")
    .replace("\\\n", "^\n")
)
POWERSHELL = (
    "$session.Cookies.Add((New-Object System.Net.Cookie("
    f'"_csrf-dtek-kem", "{COOKIE}", "/", "www.dtek-kem.com.ua")))\n'
    'Invoke-WebRequest -UseBasicParsing -Uri "https://www.dtek-kem.com.ua/ua/ajax" '
    f'-Method "POST" -WebSession $session -Headers @{{"x-csrf-token"="{TOKEN}"}} '
    f'-Body "{BODY}"'
)

EMERGENCY = {
    "sub_type": "Аварійні ремонтні роботи",
    "start_date": "05:31 14.10.2026",
    "end_date": "09:31 14.10.2026",
    "type": "2",
    "sub_type_reason": ["GPV43.1"],
    "voluntarily": None,
    "cek": None,
}
NO_OUTAGE = {
    "sub_type": "",
    "start_date": "",
    "end_date": "",
    "type": "",
    "sub_type_reason": ["GPV43.1"],
    "voluntarily": None,
    "cek": None,
}


@pytest.fixture
def street_answer():
    """Answer of the website for a street (shortened)."""
    return {
        "result": True,
        "data": {"12": EMERGENCY, "14": NO_OUTAGE},
        "updateTimestamp": "07:18 14.10.2026",
    }


def _response(status, text, cookies=None):
    response = AsyncMock()
    response.status = status
    response.text = AsyncMock(return_value=text)
    response.cookies = {
        name: MagicMock(value=value) for name, value in (cookies or {}).items()
    }
    return response


CAPTCHA = "<html><script src='/_Incapsula_Resource?SWJIYLWA=1'></script></html>"


class TestParseCredentials:
    """CSRF pair and street from a request copied from the browser."""

    @pytest.mark.parametrize(
        ("text", "imperva"),
        [
            (CURL_BASH, {"visid_incap_1": "q"}),
            (CURL_CMD, {"visid_incap_1": "q"}),
            (POWERSHELL, {}),
        ],
    )
    def test_formats(self, text, imperva):
        """Copy as cURL (bash, cmd) and Copy as PowerShell; Imperva cookies are kept."""
        credentials, street = parse_credentials(text)
        assert credentials == DtekCredentials(COOKIE, TOKEN, imperva)
        assert street == STREET

    def test_imperva_cookies(self):
        """All Imperva cookies of the request, other cookies are skipped."""
        text = (
            f"curl 'https://www.dtek-kem.com.ua/ua/ajax' -b 'dtek-kem=x; "
            f"visid_incap_2224657=AAA; incap_ses_788_2224657=BBB==; nlbi_2224657=CCC; "
            f"_ga=GA1; _csrf-dtek-kem={COOKIE}' -H 'x-csrf-token: {TOKEN}'"
        )
        credentials, _ = parse_credentials(text)
        assert credentials.imperva == {
            "visid_incap_2224657": "AAA",
            "incap_ses_788_2224657": "BBB==",
            "nlbi_2224657": "CCC",
        }
        assert credentials.cookies()["_csrf-dtek-kem"] == COOKIE

    def test_imperva_powershell(self):
        """Imperva cookie added by Copy as PowerShell."""
        text = POWERSHELL + (
            "\n$session.Cookies.Add((New-Object System.Net.Cookie("
            '"incap_ses_788_2224657", "SES", "/", ".dtek-kem.com.ua")))'
        )
        credentials, _ = parse_credentials(text)
        assert credentials.imperva == {"incap_ses_788_2224657": "SES"}

    def test_cookie_header(self):
        """Cookie in a header, no body: no street."""
        text = (
            f"curl 'https://www.dtek-kem.com.ua/ua/ajax' "
            f"-H 'cookie: a=b; _csrf-dtek-kem={COOKIE}' -H 'X-CSRF-Token: {TOKEN}'"
        )
        assert parse_credentials(text) == (DtekCredentials(COOKIE, TOKEN), None)

    def test_without_cookie(self):
        """Copy as fetch has no cookies."""
        text = f'fetch("https://www.dtek-kem.com.ua/ua/ajax", {{"x-csrf-token": "{TOKEN}"}})'
        assert parse_credentials(text) == (None, None)

    def test_empty(self):
        """Nothing pasted."""
        assert parse_credentials("") == (None, None)


class TestParseHouse:
    """Outage of the house from its item of the answer."""

    def test_emergency(self):
        """Emergency works with the estimated restoration."""
        outage = parse_house(EMERGENCY)
        assert outage.kind == AddressOutageKind.EMERGENCY
        assert outage.reason == "Аварійні ремонтні роботи"
        assert outage.start == datetime.datetime(2026, 10, 14, 5, 31, tzinfo=KYIV_TZ)
        assert outage.end == datetime.datetime(2026, 10, 14, 9, 31, tzinfo=KYIV_TZ)
        assert outage.type == "2"
        assert outage.groups == ("43.1",)

    def test_no_outage(self):
        """Empty fields: the house has electricity."""
        outage = parse_house(NO_OUTAGE)
        assert outage.kind == AddressOutageKind.NORMAL
        assert outage.reason is None
        assert outage.start is None
        assert outage.end is None

    @pytest.mark.parametrize(
        ("reason", "kind"),
        [
            ("Екстрені відключення", AddressOutageKind.EMERGENCY),
            ("Стабілізаційне відключення", AddressOutageKind.STABILIZATION),
            ("Планові ремонтні роботи", AddressOutageKind.PLANNED),
            ("Відключення", AddressOutageKind.OTHER),
        ],
    )
    def test_kind(self, reason, kind):
        """Kind of the outage by its reason."""
        assert parse_house({**EMERGENCY, "sub_type": reason}).kind == kind

    def test_bad_date(self):
        """An unknown date format is skipped."""
        outage = parse_house({**EMERGENCY, "end_date": "soon"})
        assert outage.kind == AddressOutageKind.EMERGENCY
        assert outage.end is None


class TestFetchStreet:
    """Request of a street and the errors of the website."""

    async def test_success(self, street_answer):
        """The CSRF pair goes as the cookie and the header."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.return_value.__aenter__.return_value = _response(
                200, json.dumps(street_answer)
            )
            data = await fetch_street(STREET, DtekCredentials(COOKIE, TOKEN))
        assert data == street_answer
        kwargs = mock_post.call_args.kwargs
        assert kwargs["headers"]["X-CSRF-Token"] == TOKEN
        assert kwargs["data"]["data[1][value]"] == STREET

    async def test_rejected_pair(self):
        """Yii answers 400 to a rejected CSRF pair."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.return_value.__aenter__.return_value = _response(
                400, "Bad Request (#400)"
            )
            with pytest.raises(DtekAddressAuthError):
                await fetch_street(STREET, DtekCredentials(COOKIE, TOKEN))

    async def test_unknown_street(self):
        """An unknown street: result false."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.return_value.__aenter__.return_value = _response(
                200, '{"result":false,"text":"Error"}'
            )
            with pytest.raises(DtekAddressStreetError):
                await fetch_street("Неіснуюча", DtekCredentials(COOKIE, TOKEN))

    async def test_captcha_page(self):
        """Not JSON: the Imperva page."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.return_value.__aenter__.return_value = _response(
                200, "<html><script src='/_Incapsula_Resource'></script></html>"
            )
            with pytest.raises(DtekAddressError):
                await fetch_street(STREET, DtekCredentials(COOKIE, TOKEN))


class TestDtekAddressApi:
    """The house of the address and the last answer."""

    async def test_fetch_data(self, street_answer):
        """The house and the update time from the answer."""
        api = DtekAddressApi(STREET, "12", DtekCredentials(COOKIE, TOKEN))
        with patch(
            "custom_components.svitlo_kyiv.api.dtek_address.fetch_street",
            AsyncMock(return_value=street_answer),
        ):
            await api.fetch_data()
        assert api.get_outage().kind == AddressOutageKind.EMERGENCY
        assert api.get_updated_on() == datetime.datetime(
            2026, 10, 14, 7, 18, tzinfo=KYIV_TZ
        )
        assert api.last_success is not None

    async def test_error_keeps_data(self, street_answer):
        """A failed request keeps the last answer."""
        api = DtekAddressApi(STREET, "14", DtekCredentials(COOKIE, TOKEN))
        api.data = street_answer
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = aiohttp.ClientError("boom")
            await api.fetch_data()
        assert api.data == street_answer
        assert api.get_outage().kind == AddressOutageKind.NORMAL

    async def test_rejected_pair_raises(self):
        """A rejected CSRF pair is raised for the reauth flow."""
        api = DtekAddressApi(STREET, "12", DtekCredentials(COOKIE, TOKEN))
        with (
            patch(
                "custom_components.svitlo_kyiv.api.dtek_address.fetch_street",
                AsyncMock(side_effect=DtekAddressAuthError("400")),
            ),
            pytest.raises(DtekAddressAuthError),
        ):
            await api.fetch_data()

    def test_unknown_house(self, street_answer):
        """A house not in the answer: no data."""
        api = DtekAddressApi(STREET, "999", MagicMock())
        api.data = street_answer
        assert api.get_outage() is None

    def test_no_data(self):
        """Before the first answer."""
        api = DtekAddressApi(STREET, "12", MagicMock())
        assert api.get_outage() is None
        assert api.get_updated_on() is None


class TestCaptcha:
    """Imperva captcha page: back-off, cookies, stale data."""

    async def test_captcha_page_error(self):
        """A captcha page is told apart from other errors."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.return_value.__aenter__.return_value = _response(200, CAPTCHA)
            with pytest.raises(DtekAddressCaptchaError):
                await fetch_street(STREET, DtekCredentials(COOKIE, TOKEN))

    async def test_backoff_after_captcha(self, street_answer):
        """After a captcha the next request is made in 30 minutes; success resets."""
        api = DtekAddressApi(STREET, "12", DtekCredentials(COOKIE, TOKEN))
        api.data = street_answer
        now = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=KYIV_TZ)
        target = "custom_components.svitlo_kyiv.api.dtek_address.fetch_street"
        with patch(
            target, AsyncMock(side_effect=DtekAddressCaptchaError("x"))
        ) as fetch:
            await api.fetch_data(now)
            assert api.captcha_since == now
            assert api.retry_after == now + datetime.timedelta(minutes=30)
            await api.fetch_data(now + datetime.timedelta(minutes=15))
            assert fetch.await_count == 1  # waits for retry_after
            await api.fetch_data(now + datetime.timedelta(minutes=31))
            assert fetch.await_count == 2
            assert api.captcha_since == now  # the episode goes on
        assert api.data == street_answer  # the last answer is kept
        later = now + datetime.timedelta(hours=1, minutes=5)
        with patch(target, AsyncMock(return_value=street_answer)):
            await api.fetch_data(later)
        assert api.captcha_since is None
        assert api.retry_after is None
        assert api.last_success == later

    async def test_new_imperva_cookies_kept(self, street_answer):
        """Imperva cookies set by the website are used by the next requests."""
        api = DtekAddressApi(
            STREET, "12", DtekCredentials(COOKIE, TOKEN, {"visid_incap_1": "old"})
        )
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.return_value.__aenter__.return_value = _response(
                200,
                json.dumps(street_answer),
                {"incap_ses_1_1": "new", "dtek-kem": "skip"},
            )
            await api.fetch_data()
        assert api.credentials.imperva == {
            "visid_incap_1": "old",
            "incap_ses_1_1": "new",
        }

    def test_stale(self, street_answer):
        """Without a successful answer for 2 hours the data is stale."""
        api = DtekAddressApi(STREET, "12", DtekCredentials(COOKIE, TOKEN))
        now = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=KYIV_TZ)
        assert not api.is_stale(now)  # no data yet: not stale, just unknown
        api.data = street_answer
        api.last_success = now - datetime.timedelta(hours=1)
        assert not api.is_stale(now)
        api.last_success = now - datetime.timedelta(hours=2, minutes=1)
        assert api.is_stale(now)
