"""Button platform for Svitlo Yeah integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities([UpdateScheduleButton(coordinator)])

class UpdateScheduleButton(ButtonEntity):
    _attr_name = "Update Schedule"
    _attr_icon = "mdi:refresh"
    _attr_unique_id = "update_schedule_button"
    _attr_should_poll = False

    def __init__(self, coordinator):
        self._coordinator = coordinator

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()
