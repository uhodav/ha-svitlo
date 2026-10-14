"""Diagnostics for Svitlo Yeah: raw data of the schedule sources and the address."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_utils

from .const import CONF_CSRF_COOKIE, CONF_CSRF_TOKEN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator.yasno import YasnoCoordinator

# The CSRF pair of the DTEK website works like a password
TO_REDACT = {CONF_CSRF_COOKIE, CONF_CSRF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: YasnoCoordinator = entry.runtime_data
    api = coordinator.api
    alt = coordinator.alt_api
    today = dt_utils.now().date()
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "last_schedule_request": coordinator.last_schedule_request_time,
        "schedule_updated_on": coordinator.schedule_updated_on,
        "schedule_data_changed_on": coordinator.schedule_data_changed_on,
        "schedule": api.get_schedule_by_day(today),
        "day_sources": api.day_sources,
        "yasno": {
            "region_id": api.region_id,
            "provider_id": api.provider_id,
            "group": api.group,
            "updated_on": api.get_yasno_updated_on(),
            "group_data": api._get_group_data(),  # noqa: SLF001
        },
        "dtek_website_copy": {
            "file": alt.file if alt else None,
            "updated_on": api.alt_updated_on,
            "days": api.alt_days,
            "last_update_status": ((alt.data if alt else None) or {}).get(
                "lastUpdateStatus"
            ),
        },
        "known_slots": api.known_slots,
        "dtek_address": {
            "street": address.street,
            "house": address.house,
            "auth_failed": coordinator.address_auth_failed,
            "last_success": address.last_success,
            "updated_on": address.get_updated_on(),
            "house_data": address.house_data,
        }
        if (address := coordinator.address_api)
        else None,
    }
