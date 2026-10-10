"""
Second schedule source: Baskerville42/outage-data-ua.

The project copies the DTEK website schedule (``DisconSchedule.fact``) to GitHub
every ~5 minutes. The DTEK website usually publishes a new schedule earlier than
the Yasno API, and it keeps the planned schedule during emergency shutdowns.
"""

from __future__ import annotations

import datetime
import logging
import time
from zoneinfo import ZoneInfo

import aiohttp

LOGGER = logging.getLogger(__name__)

# Days and update time in the file are in Kyiv time
KYIV_TZ = ZoneInfo("Europe/Kyiv")

OUTAGE_DATA_UA_URL = (
    "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/{file}.json"
)

# Yasno region name -> outage-data-ua file with the same group numbering
OUTAGE_DATA_UA_FILES = {
    "Київ": "kyiv",
}


def _parse_group_hours(
    group_hours: dict[str, str],
) -> list[tuple[datetime.time, datetime.time]]:
    """
    Parse group hours data into a list of outage time ranges.

    'GPV1.1': {
    '1': 'yes',
    ...
    '12': 'yes',
    '13': 'second',
    '14': 'no',
    '15': 'no',
    '16': 'no',
    '17': 'first',
    '18': 'yes',
    ...
    '24': 'yes',
    },
    """
    ranges = []
    outage_start = None

    for n in range(1, 25):  # 1 to 24
        hour = n - 1
        status = group_hours.get(str(n), "yes")

        if status == "yes":
            if outage_start is not None:
                ranges.append((outage_start, datetime.time(hour, 0)))
                outage_start = None
        else:  # "first", "no", or "second" - all are outages
            if outage_start is None:  # Start outage at appropriate time
                outage_start = (
                    datetime.time(hour, 30)
                    if status == "second"
                    else datetime.time(hour, 0)
                )
            if status == "first":  # If "first", close at hour:30 (next will be "yes")
                ranges.append((outage_start, datetime.time(hour, 30)))
                outage_start = None

    if outage_start is not None:
        ranges.append((outage_start, datetime.time(23, 59, 59)))

    return ranges


def _time_to_minutes(value: datetime.time) -> int:
    """Minutes from the start of the day; 23:59:59 is the end of the day."""
    if value == datetime.time(23, 59, 59):
        return 24 * 60
    return value.hour * 60 + value.minute


class OutageDataUaApi:
    """Schedule of one group from an outage-data-ua file."""

    def __init__(self, file: str, group: str) -> None:
        """Initialize the source."""
        self.file = file
        self.group = group
        self.data: dict | None = None

    @classmethod
    def for_region(cls, region_name: str | None, group: str) -> OutageDataUaApi | None:
        """Create the source for a Yasno region if outage-data-ua has it."""
        file = OUTAGE_DATA_UA_FILES.get(region_name or "")
        return cls(file, group) if file else None

    async def fetch_data(self) -> None:
        """Fetch the file; on an error keep the last received data."""
        # The query parameter bypasses the 5-minute CDN cache of raw.githubusercontent
        url = OUTAGE_DATA_UA_URL.format(file=self.file) + f"?t={int(time.time())}"
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response,
            ):
                response.raise_for_status()
                self.data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            LOGGER.warning("Failed to fetch outage-data-ua %s", self.file)

    def get_updated_on(self) -> datetime.datetime | None:
        """When DTEK updated the schedule (``fact.update``, Kyiv time)."""
        update = ((self.data or {}).get("fact") or {}).get("update")
        if not update:
            return None
        try:
            naive = datetime.datetime.strptime(update, "%d.%m.%Y %H:%M")  # noqa: DTZ007
        except (TypeError, ValueError):
            LOGGER.warning("Failed to parse outage-data-ua update: %s", update)
            return None
        return naive.replace(tzinfo=KYIV_TZ)

    def get_days(self) -> dict[str, list[dict]]:
        """Schedule per day as Yasno slots: {"YYYY-MM-DD": [{"start", "end", "type"}]}."""
        fact_data = ((self.data or {}).get("fact") or {}).get("data") or {}
        group_key = f"GPV{self.group}"
        days = {}
        for timestamp, day_data in fact_data.items():
            if group_key not in day_data:
                continue
            day = datetime.datetime.fromtimestamp(int(timestamp), tz=KYIV_TZ)
            days[day.date().isoformat()] = [
                {
                    "start": _time_to_minutes(start),
                    "end": _time_to_minutes(end),
                    "type": "Definite",
                }
                for start, end in _parse_group_hours(day_data[group_key])
            ]
        return days
