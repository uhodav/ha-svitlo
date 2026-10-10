"""Init file for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import ATTR_RESTORED, STATE_UNKNOWN, Platform
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_GROUP,
    CONF_MIGRATED_FROM,
    CONF_PROVIDER_TYPE,
    DOMAIN,
    LEGACY_BUTTON_UNIQUE_ID,
    OLD_DOMAIN,
    PROVIDER_TYPE_YASNO,
)
from .coordinator.yasno import YasnoCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR, Platform.BUTTON]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    LOGGER.info("Migrating config entry from version %s", config_entry.version)

    if config_entry.version == 1:
        # No migration needed for version 1
        return True

    # If we get here, it means the config entry is from a newer version
    # than we know how to handle, which shouldn't happen in normal operation
    LOGGER.warning("Unknown config entry version %s", config_entry.version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a new entry."""
    LOGGER.info("Setup entry: %s", entry)

    provider_type = entry.options.get(
        CONF_PROVIDER_TYPE,
        entry.data.get(CONF_PROVIDER_TYPE, PROVIDER_TYPE_YASNO),
    )

    # Only Kyiv (Yasno + DTEK website copy) is supported
    if provider_type != PROVIDER_TYPE_YASNO:
        LOGGER.error(
            "Provider %s is not supported anymore, only Kyiv. "
            "Delete the entry and add it again",
            provider_type,
        )
        return False

    if entry.data.get(CONF_MIGRATED_FROM):
        await _async_migrate_from_old_domain(hass, entry)

    coordinator = YasnoCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


def _new_unique_id(unique_id: str, old_entry_id: str, entry: ConfigEntry) -> str:
    """unique_id of a moved entity in this entry."""
    if unique_id.startswith(f"{old_entry_id}-"):
        return entry.entry_id + unique_id[len(old_entry_id) :]
    if unique_id == LEGACY_BUTTON_UNIQUE_ID:
        return f"{entry.entry_id}-{entry.data.get(CONF_GROUP)}-update_schedule"
    return unique_id


async def _async_migrate_from_old_domain(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """
    Move the entities of the old "svitlo" entry to this entry.

    The entity ids (and so history, automations and dashboards) stay. Entities
    can be moved only while the old integration does not run them: its code is
    removed or its entry is disabled.
    """
    old_entry_id = entry.data[CONF_MIGRATED_FROM]
    registry = er.async_get(hass)
    blocked = []
    for old in er.async_entries_for_config_entry(registry, old_entry_id):
        state = hass.states.get(old.entity_id)
        if state is not None and state.state != STATE_UNKNOWN:
            if not state.attributes.get(ATTR_RESTORED):
                blocked.append(old.entity_id)
                continue
            # Placeholder state of an entity whose integration is not loaded
            hass.states.async_remove(old.entity_id)

        new_unique_id = _new_unique_id(old.unique_id, old_entry_id, entry)
        if registry.async_get_entity_id(old.domain, DOMAIN, new_unique_id):
            continue
        # An unchanged unique_id must not be passed: HA would see it as taken
        unique_id = (
            {"new_unique_id": new_unique_id}
            if new_unique_id != old.unique_id
            else {}
        )
        registry.async_update_entity_platform(
            old.entity_id,
            DOMAIN,
            new_config_entry_id=entry.entry_id,
            new_device_id=None,
            **unique_id,
        )
        LOGGER.info("Moved %s from %s to %s", old.entity_id, OLD_DOMAIN, DOMAIN)

    if blocked:
        LOGGER.error(
            "The old integration %s still runs %s. Remove custom_components/%s "
            "or disable its entry and restart Home Assistant to move them",
            OLD_DOMAIN,
            ", ".join(blocked),
            OLD_DOMAIN,
        )
        return

    # Done: forget the old entry (its device goes with it, the entities stay here)
    hass.config_entries.async_update_entry(
        entry,
        data={k: v for k, v in entry.data.items() if k != CONF_MIGRATED_FROM},
    )
    if hass.config_entries.async_get_entry(old_entry_id):
        hass.async_create_task(hass.config_entries.async_remove(old_entry_id))


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    LOGGER.info("Unload entry: %s", entry)
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
