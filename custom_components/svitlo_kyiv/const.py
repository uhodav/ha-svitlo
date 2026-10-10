"""Constants for the Svitlo Yeah integration."""

from typing import Final

# Do not commit as True
DEBUG: Final = False

DOMAIN: Final = "svitlo_kyiv"
# Domain of this integration before the rename; its entry is migrated
OLD_DOMAIN: Final = "svitlo"
NAME: Final = "Svitlo Kyiv"

# Configuration option
CONF_REGION: Final = "region"
CONF_PROVIDER: Final = "provider"
CONF_GROUP: Final = "group"
CONF_PROVIDER_TYPE: Final = "provider_type"
CONF_UPDATE_INTERVAL: Final = "update_interval"
# Entry id of the old "svitlo" entry whose entities are moved to this entry
CONF_MIGRATED_FROM: Final = "migrated_from"

# Provider types
PROVIDER_TYPE_YASNO: Final = "yasno"

# The only supported region (Yasno region name)
KYIV_REGION: Final = "Київ"

# Provider name simplification
PROVIDER_DTEK_FULL: Final = "ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ"
PROVIDER_DTEK_SHORT: Final = "ДТЕК"

# Consts
UPDATE_INTERVAL: Final = 15
DEFAULT_UPDATE_INTERVAL: Final = 15
MIN_UPDATE_INTERVAL: Final = 1
MAX_UPDATE_INTERVAL: Final = 30

# API Endpoints
REGIONS_ENDPOINT: Final = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/regions"
)
PLANNED_OUTAGES_ENDPOINT: Final = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"

# API Block names
BLOCK_KEY_STATUS: Final = "status"

# Keys
TRANSLATION_KEY_EVENT_PLANNED_OUTAGE: Final = (
    "component.svitlo_kyiv.common.event_name_planned_outage"
)
TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE: Final = (
    "component.svitlo_kyiv.common.event_name_emergency_outage"
)
TRANSLATION_KEY_TIME_LESS_THAN_MINUTE: Final = (
    "component.svitlo_kyiv.common.time_less_than_minute"
)

# Device
DEVICE_NAME_YASNO_TRANSLATION_KEY = "device_name_yasno"

# unique_id of the Update schedule button before it was attached to the device
LEGACY_BUTTON_UNIQUE_ID: Final = "update_schedule_button"
DEVICE_MANUFACTURER = NAME
