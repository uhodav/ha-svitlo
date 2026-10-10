"""Tests for the second schedule source (outage-data-ua) and source selection."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_kyiv.api import YasnoApi
from custom_components.svitlo_kyiv.api.outage_data_ua import (
    KYIV_TZ,
    OutageDataUaApi,
    _parse_group_hours,
)
from custom_components.svitlo_kyiv.models import PlannedOutageEventType

GROUP = "43.1"
# 2026-10-10 00:00 Kyiv
DAY_TS = "1791579600"


@pytest.fixture
def outage_data_ua():
    """outage-data-ua kyiv.json (shortened)."""
    return {
        "regionId": "kyiv",
        "fact": {
            "update": "10.10.2026 14:46",
            "today": int(DAY_TS),
            "data": {
                DAY_TS: {
                    f"GPV{GROUP}": {
                        "1": "first",  # 00:00-00:30
                        **{str(n): "yes" for n in range(2, 19)},
                        "19": "no",  # 18:00
                        "20": "no",
                        "21": "no",
                        "22": "first",  # -21:30
                        "23": "yes",
                        "24": "yes",
                    },
                    "GPV4.1": {"13": "no"},
                },
            },
        },
    }


def _yasno(status, slots, updated_on="2026-10-10T10:26:15+00:00"):
    return {
        GROUP: {
            "today": {
                "slots": slots,
                "date": "2026-10-10T00:00:00+03:00",
                "status": status,
            },
            "updatedOn": updated_on,
        }
    }


def _definite(events):
    return [
        (e.start.strftime("%d %H:%M"), e.end.strftime("%H:%M"))
        for e in events
        if e.event_type == PlannedOutageEventType.DEFINITE
    ]


class TestOutageDataUaApi:
    """Parsing of outage-data-ua."""

    def test_for_region(self):
        """Only regions with the same group numbering have the source."""
        assert OutageDataUaApi.for_region("Київ", GROUP).file == "kyiv"
        assert OutageDataUaApi.for_region("Дніпро", GROUP) is None
        assert OutageDataUaApi.for_region(None, GROUP) is None

    def test_get_days(self, outage_data_ua):
        """Hours of the group become Yasno slots in minutes."""
        api = OutageDataUaApi("kyiv", GROUP)
        api.data = outage_data_ua
        assert api.get_days() == {
            "2026-10-10": [
                {"start": 0, "end": 30, "type": "Definite"},
                {"start": 1080, "end": 1290, "type": "Definite"},
            ]
        }

    def test_get_days_unknown_group(self, outage_data_ua):
        """A group the file does not have gives no days."""
        api = OutageDataUaApi("kyiv", "99.9")
        api.data = outage_data_ua
        assert api.get_days() == {}

    def test_get_updated_on(self, outage_data_ua):
        """fact.update is Kyiv time."""
        api = OutageDataUaApi("kyiv", GROUP)
        api.data = outage_data_ua
        assert api.get_updated_on() == datetime.datetime(
            2026, 10, 10, 14, 46, tzinfo=KYIV_TZ
        )

    def test_no_data(self):
        """Without data nothing is returned."""
        api = OutageDataUaApi("kyiv", GROUP)
        assert api.get_days() == {}
        assert api.get_updated_on() is None

    async def test_fetch_error_keeps_data(self, outage_data_ua):
        """A failed request keeps the last received file."""
        api = OutageDataUaApi("kyiv", GROUP)
        api.data = outage_data_ua
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.side_effect = aiohttp.ClientError("boom")
            await api.fetch_data()
        assert api.data == outage_data_ua

    async def test_fetch_success(self, outage_data_ua):
        """The file is fetched with a cache-busting parameter."""
        api = OutageDataUaApi("kyiv", GROUP)
        with patch("aiohttp.ClientSession.get") as mock_get:
            response = AsyncMock()
            response.json = AsyncMock(return_value=outage_data_ua)
            response.raise_for_status = MagicMock()
            mock_get.return_value.__aenter__.return_value = response
            await api.fetch_data()
        assert api.data == outage_data_ua
        assert "kyiv.json?t=" in mock_get.call_args.args[0]


class TestSourceSelection:
    """Yasno + outage-data-ua: the latest schedule of each day wins."""

    @pytest.fixture
    def api(self, outage_data_ua):
        """Yasno API with the second source set."""
        alt = OutageDataUaApi("kyiv", GROUP)
        alt.data = outage_data_ua
        api = YasnoApi(region_id=25, provider_id=902, group=GROUP)
        api.set_alternative(alt.get_days(), alt.get_updated_on())
        return api

    @staticmethod
    def _day():
        start = datetime.datetime(2026, 10, 10, tzinfo=KYIV_TZ)
        return start, start + datetime.timedelta(days=1)

    def test_emergency_takes_dtek_schedule(self, api):
        """Yasno emergency with empty slots: the flag plus the DTEK schedule."""
        api.planned_outage_data = _yasno("EmergencyShutdowns", [])
        events = api.get_events(*self._day())
        assert events[0].event_type == PlannedOutageEventType.EMERGENCY
        assert _definite(events) == [("10 00:00", "00:30"), ("10 18:00", "21:30")]
        assert api.day_sources == {"2026-10-10": "dtek"}

    def test_newer_dtek_wins(self, api):
        """DTEK updated later than Yasno: its schedule is used."""
        api.planned_outage_data = _yasno(
            "ScheduleApplies", [{"start": 720, "end": 930, "type": "Definite"}]
        )
        assert _definite(api.get_events(*self._day())) == [
            ("10 00:00", "00:30"),
            ("10 18:00", "21:30"),
        ]
        assert api.day_sources["2026-10-10"] == "dtek"

    def test_newer_yasno_wins(self, api):
        """Yasno updated later than DTEK: its schedule is used."""
        api.planned_outage_data = _yasno(
            "ScheduleApplies",
            [{"start": 720, "end": 930, "type": "Definite"}],
            updated_on="2026-10-10T12:00:00+00:00",  # 15:00 Kyiv, after 14:46
        )
        assert _definite(api.get_events(*self._day())) == [("10 12:00", "15:30")]
        assert api.day_sources["2026-10-10"] == "yasno"

    def test_day_only_in_dtek(self, api):
        """A day that Yasno does not have yet comes from DTEK."""
        api.planned_outage_data = {
            GROUP: {"updatedOn": "2026-10-09T17:17:46+00:00"}
        }
        assert _definite(api.get_events(*self._day())) == [
            ("10 00:00", "00:30"),
            ("10 18:00", "21:30"),
        ]

    def test_updated_on_is_latest(self, api):
        """Schedule Updated On shows the latest of the sources."""
        api.planned_outage_data = _yasno("ScheduleApplies", [])
        assert api.get_updated_on() == datetime.datetime(
            2026, 10, 10, 14, 46, tzinfo=KYIV_TZ
        )

    def test_without_second_source(self):
        """Without the second source Yasno works as before."""
        api = YasnoApi(region_id=25, provider_id=902, group=GROUP)
        api.planned_outage_data = _yasno(
            "ScheduleApplies", [{"start": 720, "end": 930, "type": "Definite"}]
        )
        assert _definite(api.get_events(*self._day())) == [("10 12:00", "15:30")]
        assert api.get_updated_on() == dt_utils.as_local(
            dt_utils.parse_datetime("2026-10-10T10:26:15+00:00")
        )

    def test_schedule_by_day(self, api):
        """Planned outages of today and later, the end of the day as 24:00."""
        api.planned_outage_data = _yasno("EmergencyShutdowns", [])
        assert api.get_schedule_by_day(datetime.date(2026, 10, 10)) == {
            "2026-10-10": ["00:00-00:30", "18:00-21:30"]
        }
        # Past days are not part of the schedule
        assert api.get_schedule_by_day(datetime.date(2026, 10, 11)) == {}

    def test_schedule_by_day_end_of_day(self, api):
        """An outage until midnight ends at 24:00."""
        api.alt_days = {}
        api.planned_outage_data = _yasno(
            "ScheduleApplies",
            [{"start": 1260, "end": 1440, "type": "Definite"}],
            updated_on="2026-10-10T12:00:00+00:00",
        )
        assert api.get_schedule_by_day(datetime.date(2026, 10, 10)) == {
            "2026-10-10": ["21:00-24:00"]
        }

    def test_remember_slots_keeps_dtek_schedule(self, api):
        """The chosen schedule is remembered for a later emergency."""
        api.planned_outage_data = _yasno("EmergencyShutdowns", [])
        api.remember_slots(today=datetime.date(2026, 10, 10))
        assert api.known_slots["2026-10-10"] == api.alt_days["2026-10-10"]


class TestParseGroupHours:
    """Test _parse_group_hours method."""

    @pytest.mark.parametrize(
        "group_hours,expected",  # noqa: PT006
        [
            # 0 All yes - no outages
            ({str(i): "yes" for i in range(1, 25)}, []),
            # 1 All no - full day outage
            (
                {str(i): "no" for i in range(1, 25)},
                [(datetime.time(0, 0), datetime.time(23, 59, 59))],
            ),
            # 2 One range of no
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "14": "no",
                    "15": "no",
                    "16": "no",
                },
                [(datetime.time(13, 0), datetime.time(16, 0))],
            ),
            # 3 Two ranges of no
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "9": "no",
                    "10": "no",
                    "20": "no",
                    "21": "no",
                },
                [
                    (datetime.time(8, 0), datetime.time(10, 0)),
                    (datetime.time(19, 0), datetime.time(21, 0)),
                ],
            ),
            # 4 One range: second + no + first
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "13": "second",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                    "17": "first",
                },
                [(datetime.time(12, 30), datetime.time(16, 30))],
            ),
            # 5 Two ranges: second + no + first
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "9": "second",
                    "10": "no",
                    "11": "first",
                    "20": "second",
                    "21": "no",
                    "22": "first",
                },
                [
                    (datetime.time(8, 30), datetime.time(10, 30)),
                    (datetime.time(19, 30), datetime.time(21, 30)),
                ],
            ),
            # 6 Adjacent second + first
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "21": "second",
                    "22": "first",
                },
                [(datetime.time(20, 30), datetime.time(21, 30))],
            ),
        ],
    )
    def test_parse_group_hours(self, group_hours, expected):
        """Test parsing various group hour patterns."""
        result = _parse_group_hours(group_hours)
        assert result == expected
