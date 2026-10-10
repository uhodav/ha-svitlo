"""Button platform for Svitlo Yeah integration."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LEGACY_BUTTON_UNIQUE_ID
from .coordinator.yasno import YasnoCoordinator
from .entity import IntegrationEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Svitlo Yeah button platform."""
    coordinator: YasnoCoordinator = config_entry.runtime_data
    button = UpdateScheduleButton(coordinator)

    # Keep the entity_id of the old device-less button
    registry = er.async_get(hass)
    legacy_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, LEGACY_BUTTON_UNIQUE_ID
    )
    if legacy_entity_id and not registry.async_get_entity_id(
        "button", DOMAIN, button.unique_id
    ):
        registry.async_update_entity(
            legacy_entity_id,
            new_unique_id=button.unique_id,
            config_entry_id=config_entry.entry_id,
        )

    async_add_entities([button])


class UpdateScheduleButton(IntegrationEntity, ButtonEntity):
    """Request the outage schedule right now."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: YasnoCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = ButtonEntityDescription(
            key="update_schedule",
            translation_key="update_schedule",
            icon="mdi:refresh",
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-"
            f"{coordinator.group}-"
            f"{self.entity_description.key}"
        )

    @property
    def available(self) -> bool:
        """The button works even when the last request failed."""
        return True

    async def async_press(self) -> None:
        """Fetch the schedule immediately."""
        await self.coordinator.async_refresh()
