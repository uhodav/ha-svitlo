"""Yasno API client for Svitlo Yeah integration."""

from __future__ import annotations

import datetime
import logging

import aiohttp
from aiohttp.client_exceptions import ClientConnectorDNSError
from homeassistant.util import dt as dt_utils

from ..const import (
    BLOCK_KEY_STATUS,
    PLANNED_OUTAGES_ENDPOINT,
    REGIONS_ENDPOINT,
)
from .outage_data_ua import KYIV_TZ
from ..models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoPlannedOutageDayStatus,
)

LOGGER = logging.getLogger(__name__)


def _minutes_to_time(minutes: int, dt: datetime.datetime) -> datetime.datetime:
    """Convert minutes from start of day to datetime."""
    hours = minutes // 60
    mins = minutes % 60

    # Handle end of day (24:00) - keep it as 23:59:59 to stay on same day
    if hours == 24:  # noqa: PLR2004
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    return dt.replace(hour=hours, minute=mins, second=0, microsecond=0)


def _parse_day_schedule(
    day_data: dict, dt: datetime.datetime
) -> list[PlannedOutageEvent]:
    """
    Parse schedule for a single day.

    {
      "3.1": {
        "today": {
          "slots": [
            {
              "start": 0,
              "end": 960,
              "type": "NotPlanned"
            },
            {
              "start": 960,
              "end": 1200,
              "type": "Definite"
            },
            {
              "start": 1200,
              "end": 1440,
              "type": "NotPlanned"
            }
          ],
          "date": "2025-10-27T00:00:00+02:00",
          "status": "ScheduleApplies"
        },
        "tomorrow": {
          "slots": [
            {
              "start": 0,
              "end": 900,
              "type": "NotPlanned"
            },
            {
              "start": 900,
              "end": 1080,
              "type": "Definite"
            },
            {
              "start": 1080,
              "end": 1440,
              "type": "NotPlanned"
            }
          ],
          "date": "2025-10-28T00:00:00+02:00",
          "status": "WaitingForSchedule"
        },
        "updatedOn": "2025-10-27T13:42:41+00:00"
      },
    }
    """
    events = []
    slots = day_data.get("slots", [])

    for slot in slots:
        start_minutes = slot["start"]
        end_minutes = slot["end"]
        slot_type = slot["type"]

        # parse only outages
        if slot_type not in [PlannedOutageEventType.DEFINITE.value]:
            continue

        event_start = _minutes_to_time(start_minutes, dt)
        event_end = _minutes_to_time(end_minutes, dt)

        events.append(
            PlannedOutageEvent(
                start=event_start,
                end=event_end,
                event_type=PlannedOutageEventType(slot_type),
            ),
        )

    return events


class YasnoApi:
    """Class to interact with Yasno API."""

    _cached_regions_data: list[dict] | None = None

    def __init__(
        self,
        region_id: int | None = None,
        provider_id: int | None = None,
        group: str | None = None,
    ) -> None:
        """Initialize the Yasno API."""
        self.region_id = region_id
        self.provider_id = provider_id
        self.group = group
        self.regions_data = None
        self.planned_outage_data = None
        # Last known schedule slots per day ("YYYY-MM-DD" -> slots). Emergency
        # shutdowns come with empty slots, but they are only a flag: the planned
        # schedule for the day still applies.
        self.known_slots: dict[str, list[dict]] = {}
        # Second source (DTEK website copy): slots per day and its update time
        self.alt_days: dict[str, list[dict]] = {}
        self.alt_updated_on: datetime.datetime | None = None
        # Which source gave the schedule of each day: yasno / dtek / known
        self.day_sources: dict[str, str] = {}

    async def _get_route_data(
        self,
        session: aiohttp.ClientSession,
        url: str,
        timeout_secs: int = 60,
    ) -> dict | list[dict] | None:
        """Fetch data from the given URL."""
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_secs),
                # Ask intermediate caches for the current schedule
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as response:
                response.raise_for_status()
                return await response.json()

        except ClientConnectorDNSError:
            LOGGER.warning("DNS timeout or resolution failed for %s", url)
            return None
        except aiohttp.ClientError:
            LOGGER.exception("Error fetching data from %s", url)
            return None

    async def fetch_yasno_regions(self) -> None:
        """Fetch regions and providers data."""
        if YasnoApi._cached_regions_data:
            self.regions_data = YasnoApi._cached_regions_data
            return

        async with aiohttp.ClientSession() as session:
            self.regions_data = (
                YasnoApi._cached_regions_data
            ) = await self._get_route_data(session, REGIONS_ENDPOINT)

    async def fetch_planned_outage_data(self) -> None:
        """Fetch outage data for the configured region and provider."""
        if not self.region_id or not self.provider_id:
            LOGGER.warning(
                "Region ID and Provider ID must be set before fetching outages",
            )
            return

        url = PLANNED_OUTAGES_ENDPOINT.format(
            region_id=self.region_id,
            dso_id=self.provider_id,
        )
        async with aiohttp.ClientSession() as session:
            data = await self._get_route_data(session, url)
        # On a request error keep the last received schedule
        if data is not None:
            self.planned_outage_data = data

        # DEBUG. DO NOT COMMIT UNCOMMENTED!
        """
        self.planned_outage_data = {
            "3.1": {
                "today": {
                    "slots": [],
                    "date": "2025-10-27T00:00:00+02:00",
                    "status": "EmergencyShutdowns"
                },
                "tomorrow": {
                    "slots": [],
                    "date": "2025-10-28T00:00:00+02:00",
                    "status": "EmergencyShutdowns"
                },
                "updatedOn": "2025-10-27T07:04:31+00:00"
            }
        }
        """
        # DEBUG. DO NOT COMMIT UNCOMMENTED!

    def get_yasno_regions(self) -> list[dict]:
        """Get a list of available regions."""
        if not self.regions_data:
            return []

        return self.regions_data

    def get_region_by_name(self, region_name: str) -> dict | None:
        """Get region data by name."""
        for region in self.get_yasno_regions():
            if region["value"] == region_name:
                return region

        return None

    def get_yasno_providers_for_region(self, region_name: str) -> list[dict]:
        """Get providers for a specific region."""
        region = self.get_region_by_name(region_name)
        if not region:
            return []

        return region.get("dsos", [])

    def get_yasno_provider_by_name(
        self, region_name: str, provider_name: str
    ) -> dict | None:
        """Get provider data by region and provider name."""
        providers = self.get_yasno_providers_for_region(region_name)
        for provider in providers:
            if provider["name"] == provider_name:
                return provider

        return None

    def get_yasno_groups(self) -> list[str]:
        """Get groups from planned outage data."""
        if not self.planned_outage_data:
            return []

        return list(self.planned_outage_data.keys())

    def _get_group_data(self) -> dict | None:
        """
        Get data for the configured group.

        {
          'today': {
            'slots': [
              {
                'start': 0,
                'end': 1140,
                'type': 'NotPlanned'
              },
              {
                'start': 1140,
                'end': 1320,
                'type': 'Definite'
              },
              {
                'start': 1320,
                'end': 1440,
                'type': 'NotPlanned'
              }
            ],
            'date': '2025-10-28T00:00:00+02:00',
            'status': 'ScheduleApplies'
          },
          'tomorrow': {
            'slots': [
              {
                'start': 0,
                'end': 960,
                'type': 'NotPlanned'
              },
              {
                'start': 960,
                'end': 1200,
                'type': 'Definite'
              },
              {
                'start': 1200,
                'end': 1440,
                'type': 'NotPlanned'
              }
            ],
            'date': '2025-10-29T00:00:00+02:00',
            'status': 'WaitingForSchedule'
          },
          'updatedOn': '2025-10-28T10:23:56+00:00'
        }
        """
        if not self.planned_outage_data or self.group not in self.planned_outage_data:
            return None

        return self.planned_outage_data[self.group]

    def get_updated_on(self) -> datetime.datetime | None:
        """When the schedule in use was updated (the latest of the sources)."""
        times = [t for t in (self.get_yasno_updated_on(), self.alt_updated_on) if t]
        return max(times) if times else None

    def set_alternative(
        self, days: dict[str, list[dict]], updated_on: datetime.datetime | None
    ) -> None:
        """Set the schedule of the second source (DTEK website copy)."""
        self.alt_days = days
        self.alt_updated_on = dt_utils.as_local(updated_on) if updated_on else None

    def _choose_slots(
        self, day: str, status: str | None, slots: list[dict]
    ) -> tuple[list[dict], str]:
        """
        Pick the schedule of a day: (slots, source).

        The second source wins when Yasno has no schedule for the day (empty
        slots, e.g. during emergency shutdowns) or when it was updated later.
        Without both, the last known schedule of the day is used.
        """
        alt = self.alt_days.get(day)
        yasno_updated = self.get_yasno_updated_on()
        if alt is not None and (
            not slots
            or (
                self.alt_updated_on
                and yasno_updated
                and self.alt_updated_on > yasno_updated
            )
        ):
            return alt, "dtek"
        if slots:
            return slots, "yasno"
        if status == YasnoPlannedOutageDayStatus.STATUS_EMERGENCY_SHUTDOWNS.value:
            return self.known_slots.get(day, []), "known"
        return [], "yasno"

    def get_yasno_updated_on(self) -> datetime.datetime | None:
        """Get the updated on timestamp for the configured group."""
        group_data = self._get_group_data()
        if not group_data or "updatedOn" not in group_data:
            return None

        try:
            updated_on = dt_utils.parse_datetime(group_data["updatedOn"])
            if updated_on:
                return dt_utils.as_local(updated_on)
        except (ValueError, TypeError):
            LOGGER.warning(
                "Failed to parse updatedOn timestamp: %s",
                group_data["updatedOn"],
            )
            return None

    def get_current_event(self, at: datetime.datetime) -> PlannedOutageEvent | None:
        """Get the current event."""
        all_events = self.get_events(at, at + datetime.timedelta(days=1))
        for event in all_events:
            if event.all_day and event.start == at.date():
                return event
            if not event.all_day and event.start <= at < event.end:
                return event

        return None

    def get_events(
        self, start_date: datetime.datetime, end_date: datetime.datetime
    ) -> list[PlannedOutageEvent]:
        """Get all events within the date range."""
        group_data = self._get_group_data()
        if not group_data:
            return []

        LOGGER.debug("Group data for %s: %s", self.group, group_data)

        events = []
        self.day_sources = {}
        yasno_days = set()
        for key, day_data in group_data.items():
            # parse only "today" and "tomorrow"
            if key == "updatedOn" or not isinstance(day_data, dict):
                continue

            date_str = day_data.get("date")
            if not date_str:
                continue

            day_dt = dt_utils.parse_datetime(date_str)
            if not day_dt:
                continue

            status = day_data.get(BLOCK_KEY_STATUS)
            day = day_dt.date().isoformat()
            yasno_days.add(day)
            # Emergency is only a flag - the planned schedule of the day stays
            slots, self.day_sources[day] = self._choose_slots(
                day, status, day_data.get("slots") or []
            )
            if status == YasnoPlannedOutageDayStatus.STATUS_EMERGENCY_SHUTDOWNS.value:
                """
                {
                    "3.1": {
                        "today": {
                            "slots": [],
                            "date": "2025-10-27T00:00:00+02:00",
                            "status": "EmergencyShutdowns"
                        },
                        "tomorrow": {
                            "slots": [],
                            "date": "2025-10-28T00:00:00+02:00",
                            "status": "EmergencyShutdowns"
                        },
                        "updatedOn": "2025-10-27T07:04:31+00:00"
                    }
                }
                """
                events.append(
                    PlannedOutageEvent(
                        start=day_dt.date(),
                        end=day_dt.date(),
                        all_day=True,
                        event_type=PlannedOutageEventType.EMERGENCY,
                    )
                )
            # ScheduleApplies, WaitingForSchedule (still contains schedule data)
            # and the planned schedule behind the emergency flag
            events.extend(_parse_day_schedule({"slots": slots}, day_dt))

        # Days that only the second source has (e.g. tomorrow published earlier)
        for day, slots in self.alt_days.items():
            if day in yasno_days:
                continue
            day_dt = datetime.datetime.combine(
                datetime.date.fromisoformat(day),
                datetime.time.min,
                tzinfo=KYIV_TZ,
            )
            self.day_sources[day] = "dtek"
            events.extend(_parse_day_schedule({"slots": slots}, day_dt))

        # By day; within a day the all-day (emergency) flag first, then by time
        events.sort(
            key=lambda e: (
                (e.start, 0, 0.0) if e.all_day else (e.start.date(), 1, e.start.timestamp())
            )
        )

        return [
            e
            for e in events
            if e.all_day or not (e.end <= start_date or e.start >= end_date)
        ]

    def get_schedule_by_day(self, today: datetime.date) -> dict[str, list[str]]:
        """
        Planned outages of today and later: {"YYYY-MM-DD": ["HH:MM-HH:MM", ...]}.

        Used to detect a real change of the schedule (not just a new response).
        """
        start = datetime.datetime.combine(today, datetime.time.min, tzinfo=KYIV_TZ)
        schedule: dict[str, list[str]] = {}
        for event in self.get_events(start, start + datetime.timedelta(days=2)):
            if event.all_day or event.event_type != PlannedOutageEventType.DEFINITE:
                continue
            day = event.start.date()
            if day < today:
                continue
            end = event.end.strftime("%H:%M")
            if event.end.date() != day or end == "23:59":
                end = "24:00"
            schedule.setdefault(day.isoformat(), []).append(
                f"{event.start.strftime('%H:%M')}-{end}"
            )
        return schedule

    def remember_slots(self, today: datetime.date | None = None) -> bool:
        """
        Remember the schedule slots of each day for emergency shutdowns.

        Returns True if the known slots changed.
        """
        group_data = self._get_group_data() or {}
        known = dict(self.known_slots)
        for key, day_data in group_data.items():
            if key == "updatedOn" or not isinstance(day_data, dict):
                continue
            day_dt = dt_utils.parse_datetime(day_data.get("date") or "")
            if not day_dt:
                continue
            day = day_dt.date().isoformat()
            slots, _ = self._choose_slots(
                day, day_data.get(BLOCK_KEY_STATUS), day_data.get("slots") or []
            )
            if slots:
                known[day] = slots
        for day, slots in self.alt_days.items():
            known.setdefault(day, slots)

        # Keep only today and later
        today = today or dt_utils.now().date()
        known = {
            day: slots for day, slots in known.items() if day >= today.isoformat()
        }

        changed = known != self.known_slots
        self.known_slots = known
        return changed

    async def fetch_data(self) -> None:
        """Fetch all required data."""
        await self.fetch_planned_outage_data()
