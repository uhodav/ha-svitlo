"""Sensor platform for Svitlo Yeah integration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.dtek_address import AddressOutageKind
from .const import DOMAIN
from .coordinator.yasno import YasnoCoordinator
from .entity import IntegrationEntity
from .models import ConnectivityState

from homeassistant.helpers.restore_state import RestoreEntity
import datetime

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class IntegrationSensorDescription(SensorEntityDescription):
    """Yasno Outages entity description."""

    val_func: Callable[[YasnoCoordinator], Any]
    available_func: Callable[[YasnoCoordinator], bool] | None = None
    attr_func: Callable[[YasnoCoordinator], dict[str, Any]] | None = None


SENSOR_TYPES: tuple[IntegrationSensorDescription, ...] = (
    IntegrationSensorDescription(
        key="electricity",
        translation_key="electricity",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.ENUM,
        options=[str(_.value) for _ in ConnectivityState],
        val_func=lambda coordinator: coordinator.current_state,
    ),
    IntegrationSensorDescription(
        key="current_day_status",
        translation_key="current_day_status",
        icon="mdi:calendar-today",
        device_class=SensorDeviceClass.ENUM,
        options=["ScheduleApplies", "EmergencyShutdowns", "NoOutages"],
        val_func=lambda coordinator: coordinator.current_day_status,
    ),
    IntegrationSensorDescription(
        key="next_outage_type",
        translation_key="next_outage_type",
        icon="mdi:alert-circle",
        device_class=SensorDeviceClass.ENUM,
        options=["Definite", "Emergency", "NotPlanned"],
        val_func=lambda coordinator: coordinator.next_outage_type,
    ),
    # Schedule and timing sensors
    IntegrationSensorDescription(
        key="schedule_updated_on",
        translation_key="schedule_updated_on",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.schedule_updated_on,
    ),
    IntegrationSensorDescription(
        key="schedule_data_changed_on",
        translation_key="schedule_data_changed_on",
        icon="mdi:calendar-edit",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.schedule_data_changed_on,
    ),
    IntegrationSensorDescription(
        key="next_planned_outage",
        translation_key="next_planned_outage",
        icon="mdi:calendar-remove",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_planned_outage,
    ),
    IntegrationSensorDescription(
        key="next_connectivity",
        translation_key="next_connectivity",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_connectivity,
    ),
    IntegrationSensorDescription(
        key="next_planned_reconnection",
        translation_key="next_planned_reconnection",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_planned_reconnection,
    ),
    # Time detail sensors
    IntegrationSensorDescription(
        key="next_planned_outage_start_time",
        translation_key="next_planned_outage_start_time",
        icon="mdi:clock-start",
        val_func=lambda coordinator: coordinator.next_planned_outage_start_time,
    ),
    IntegrationSensorDescription(
        key="next_planned_outage_end_time",
        translation_key="next_planned_outage_end_time",
        icon="mdi:clock-end",
        val_func=lambda coordinator: coordinator.next_planned_outage_end_time,
    ),
    # Duration and countdown sensors
    IntegrationSensorDescription(
        key="next_planned_outage_duration",
        translation_key="next_planned_outage_duration",
        icon="mdi:timer",
        native_unit_of_measurement="min",
        val_func=lambda coordinator: coordinator.next_planned_outage_duration,
    ),
    IntegrationSensorDescription(
        key="time_until_connectivity",
        translation_key="time_until_connectivity",
        icon="mdi:clock-outline",
        val_func=lambda coordinator: coordinator.time_until_connectivity,
    ),

    IntegrationSensorDescription(
        key="time_until_outage",
        translation_key="time_until_outage",
        icon="mdi:clock-alert-outline",
        val_func=lambda coordinator: coordinator.time_until_outage,
    ),
    IntegrationSensorDescription(
        key="last_schedule_request",
        translation_key="last_schedule_request",
        icon="mdi:clock",
        val_func=lambda coordinator: _format_last_schedule_request(getattr(coordinator, "last_schedule_request_time", None)),
    ),
)


def _address_attributes(coordinator: YasnoCoordinator) -> dict[str, Any]:
    """Details of the outage of the house."""
    outage = coordinator.address_outage
    api = coordinator.address_api
    return {
        "street": api.street,
        "house": api.house,
        "reason": outage.reason if outage else None,
        "start": outage.start if outage else None,
        "end": outage.end if outage else None,
        "type": outage.type if outage else None,
        "groups": list(outage.groups) if outage else [],
        "dtek_updated_on": api.get_updated_on(),
        "last_success": api.last_success,
    }


def _address_available(coordinator: YasnoCoordinator) -> bool:
    """Return whether the address has data (and its CSRF pair is accepted)."""
    return coordinator.address_outage is not None


def _address_value(coordinator: YasnoCoordinator, field: str) -> Any:
    """Return a field of the outage of the house."""
    outage = coordinator.address_outage
    return getattr(outage, field) if outage else None


# Created only when the entry has the address of the DTEK website
ADDRESS_SENSOR_TYPES: tuple[IntegrationSensorDescription, ...] = (
    IntegrationSensorDescription(
        key="address_outage",
        translation_key="address_outage",
        icon="mdi:home-lightning-bolt",
        device_class=SensorDeviceClass.ENUM,
        options=[str(_.value) for _ in AddressOutageKind],
        val_func=lambda coordinator: _address_value(coordinator, "kind"),
        available_func=_address_available,
        attr_func=_address_attributes,
    ),
    IntegrationSensorDescription(
        key="address_outage_start",
        translation_key="address_outage_start",
        icon="mdi:home-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: _address_value(coordinator, "start"),
        available_func=_address_available,
    ),
    IntegrationSensorDescription(
        key="address_outage_end",
        translation_key="address_outage_end",
        icon="mdi:home-clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: _address_value(coordinator, "end"),
        available_func=_address_available,
    ),
)


def _format_last_schedule_request(dt_str):
    if not dt_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return dt_str

# Sensor for last schedule request time

# Сенсор времени последнего обновления графика
class LastScheduleRequestSensor(SensorEntity, RestoreEntity):
    _attr_name = "Last Schedule Request"
    _attr_icon = "mdi:clock"
    _attr_unique_id = "last_schedule_request"
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = True
    _attr_entity_category = None

    def __init__(self, coordinator: YasnoCoordinator):
        super().__init__()
        self._coordinator = coordinator
        self._attr_native_value = None
        self._unsub = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        # Подписка на обновления coordinator
        if hasattr(self._coordinator, "async_add_listener"):
            self._unsub = self._coordinator.async_add_listener(self._handle_refresh)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
        await super().async_will_remove_from_hass()

    def _handle_refresh(self):
        self._attr_native_value = datetime.datetime.now().isoformat()
        self.async_write_ha_state()

    @property
    def state(self):
        return self._attr_native_value


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    LOGGER.debug("Setup new sensor: %s", config_entry)
    coordinator: YasnoCoordinator = config_entry.runtime_data
    descriptions = SENSOR_TYPES
    if coordinator.address_api is not None:
        descriptions += ADDRESS_SENSOR_TYPES
    else:
        # The address was removed in the options: remove its sensors
        registry = er.async_get(hass)
        for description in ADDRESS_SENSOR_TYPES:
            unique_id = f"{config_entry.entry_id}-{coordinator.group}-{description.key}"
            if entity_id := registry.async_get_entity_id("sensor", DOMAIN, unique_id):
                registry.async_remove(entity_id)
    entities = [
        IntegrationSensor(coordinator, description) for description in descriptions
    ]
    entities.append(LastScheduleRequestSensor(coordinator))
    async_add_entities(entities)


class IntegrationSensor(IntegrationEntity, SensorEntity):
    """Implementation of sensor entity."""

    entity_description: IntegrationSensorDescription

    def __init__(
        self,
        coordinator: YasnoCoordinator,
        entity_description: IntegrationSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-"
            f"{coordinator.group}-"
            f"{self.entity_description.key}"
        )

    @property
    def available(self) -> bool:
        """Address sensors need the data of the address."""
        available_func = self.entity_description.available_func
        if available_func is not None and not available_func(self.coordinator):
            return False
        return super().available

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.entity_description.val_func(self.coordinator)

    @property
    def icon(self) -> str | None:
        """Return the icon of the sensor."""
        # Dynamic icons for electricity sensor
        if self.entity_description.key == "electricity":
            state = self.native_value
            if state == ConnectivityState.STATE_NORMAL.value:
                return "mdi:transmission-tower"
            if state == ConnectivityState.STATE_PLANNED_OUTAGE.value:
                return "mdi:transmission-tower-off"
            if state == ConnectivityState.STATE_EMERGENCY.value:
                return "mdi:alert-octagon"

        return self.entity_description.icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes for the electricity sensor."""
        if self.entity_description.attr_func is not None:
            return self.entity_description.attr_func(self.coordinator)
        if self.entity_description.key != "electricity":
            return None

        # Get the current event to provide additional context
        current_event = self.coordinator.get_current_event()
        return {
            "event_type": current_event.description if current_event else None,
            "event_start": current_event.start if current_event else None,
            "event_end": current_event.end if current_event else None,
            "supported_states": self.options,
            # Source of the schedule of each day: yasno / dtek / known
            "schedule_sources": dict(getattr(self.coordinator.api, "day_sources", {})),
        }
