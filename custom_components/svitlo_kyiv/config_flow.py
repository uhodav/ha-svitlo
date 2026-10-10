"""Config flow for Svitlo Yeah integration (Kyiv only)."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .api.yasno import YasnoApi
from .const import (
    CONF_GROUP,
    CONF_MIGRATED_FROM,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    KYIV_REGION,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    NAME,
    OLD_DOMAIN,
    PROVIDER_TYPE_YASNO,
)

LOGGER = logging.getLogger(__name__)


def get_config_value(
    entry: ConfigEntry | None,
    key: str,
    default: Any = None,
) -> Any:
    """Get a value from the config entry or default."""
    if entry is not None:
        return entry.options.get(key, entry.data.get(key, default))
    return default


def build_group_schema(
    groups: list[str],
    config_entry: ConfigEntry | None,
) -> vol.Schema:
    """Build the schema for the group selection step."""
    return vol.Schema(
        {
            vol.Required(
                CONF_GROUP,
                default=get_config_value(config_entry, CONF_GROUP),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=groups,
                    translation_key="group",
                ),
            ),
        },
    )


class IntegrationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Svitlo Yeah: Kyiv, DTEK Kyiv grids, a group."""

    VERSION = 1  # Config entry version for migration handling

    def __init__(self) -> None:
        """Initialize config flow."""
        self.api_yasno = YasnoApi()
        self.data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "IntegrationOptionsFlow":
        """Create the options flow."""
        return IntegrationOptionsFlow(config_entry)

    def _old_entries(self) -> list[ConfigEntry]:
        """Kyiv entries of the integration before the rename (domain "svitlo")."""
        migrated = {
            entry.data.get(CONF_MIGRATED_FROM)
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        }
        return [
            entry
            for entry in self.hass.config_entries.async_entries(OLD_DOMAIN)
            if entry.data.get(CONF_REGION) == KYIV_REGION
            and entry.data.get(CONF_PROVIDER_TYPE, PROVIDER_TYPE_YASNO)
            == PROVIDER_TYPE_YASNO
            and entry.entry_id not in migrated
        ]

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Migrate the old "svitlo" entry or select a group."""
        if self._old_entries():
            # noinspection PyTypeChecker
            return self.async_show_menu(
                step_id="user", menu_options=["migrate", "group"]
            )
        # noinspection PyTypeChecker
        return await self.async_step_group()

    async def async_step_migrate(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Take over the old "svitlo" entry: same settings and entity ids."""
        old = self._old_entries()[0]
        if user_input is not None:
            data = {**old.data, CONF_MIGRATED_FROM: old.entry_id}
            # noinspection PyTypeChecker
            return self.async_create_entry(
                title=NAME, data=data, options=dict(old.options)
            )

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="migrate",
            description_placeholders={
                "title": old.title,
                "group": str(old.data.get(CONF_GROUP)),
            },
        )

    async def async_step_group(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Select the group of Kyiv."""
        if user_input is not None:
            LOGGER.debug("Group selected: %s", user_input)
            self.data.update(user_input)
            self.data.setdefault(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            # noinspection PyTypeChecker
            return self.async_create_entry(title=NAME, data=self.data)

        await self.api_yasno.fetch_yasno_regions()
        providers = self.api_yasno.get_yasno_providers_for_region(KYIV_REGION)
        region_data = self.api_yasno.get_region_by_name(KYIV_REGION)
        if not region_data or not providers:
            # noinspection PyTypeChecker
            return self.async_abort(reason="cannot_connect")

        # Kyiv has a single distribution system operator: DTEK Kyiv grids
        self.data = {
            CONF_REGION: KYIV_REGION,
            CONF_PROVIDER: providers[0]["name"],
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
        }
        api = YasnoApi(region_id=region_data["id"], provider_id=providers[0]["id"])
        await api.fetch_planned_outage_data()
        groups = api.get_yasno_groups()
        if not groups:
            # noinspection PyTypeChecker
            return self.async_abort(reason="cannot_connect")

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="group",
            data_schema=build_group_schema(groups, None),
        )


class IntegrationOptionsFlow(OptionsFlow):
    """Handle options flow for Svitlo Yeah."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=get_config_value(
                            self._config_entry,
                            CONF_UPDATE_INTERVAL,
                            DEFAULT_UPDATE_INTERVAL,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            mode=NumberSelectorMode.SLIDER,
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                        )
                    ),
                }
            ),
        )
