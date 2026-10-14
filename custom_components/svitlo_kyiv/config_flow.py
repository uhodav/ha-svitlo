"""Config flow for Svitlo Yeah integration (Kyiv only)."""

import logging
import re
from collections.abc import Mapping
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
    TextSelector,
    TextSelectorConfig,
)

from .api.dtek_address import (
    DtekAddressAuthError,
    DtekAddressError,
    DtekAddressStreetError,
    DtekCredentials,
    fetch_street,
    parse_credentials,
)
from .api.yasno import YasnoApi
from .const import (
    ADDRESS_KEYS,
    CONF_CSRF_COOKIE,
    CONF_CSRF_TOKEN,
    CONF_GROUP,
    CONF_HOUSE,
    CONF_MIGRATED_FROM,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    CONF_REQUEST,
    CONF_STREET,
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

REQUEST_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))


def _house_sort_key(house: str) -> tuple[int, str]:
    """Natural order of houses: by the leading number, then by the name."""
    match = re.match(r"\d+", house)
    return (int(match.group()) if match else 10**6, house)


async def validate_request(
    request: str, street: str | None
) -> tuple[dict[str, str], DtekCredentials | None, str | None, list[str]]:
    """
    Check a request copied from the browser against the DTEK website.

    Returns (errors, credentials, street, houses of the street).
    """
    credentials, request_street = parse_credentials(request or "")
    street = (street or "").strip() or request_street
    if credentials is None:
        return {CONF_REQUEST: "invalid_request"}, None, street, []
    if not street:
        return {CONF_STREET: "street_required"}, credentials, None, []
    try:
        data = await fetch_street(street, credentials)
    except DtekAddressAuthError:
        return {CONF_REQUEST: "invalid_auth"}, credentials, street, []
    except DtekAddressStreetError:
        return {CONF_STREET: "street_not_found"}, credentials, street, []
    except DtekAddressError:
        LOGGER.exception("DTEK website request failed")
        return {"base": "cannot_connect_dtek"}, credentials, street, []
    houses = sorted(data["data"], key=_house_sort_key)
    return {}, credentials, street, houses


class AddressFlowMixin:
    """
    Steps «address» and «house»: the address of the DTEK website (optional).

    The flow sets ``_address_defaults`` and implements ``_address_done``.
    """

    _address_defaults: Mapping[str, Any]
    _credentials: DtekCredentials | None = None
    _street: str | None = None
    _houses: list[str]

    async def _address_done(self, address: dict[str, str] | None) -> ConfigFlowResult:
        """Finish the flow with the address (None: without the address)."""
        raise NotImplementedError

    async def async_step_address(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Paste the request of the address form of the DTEK website."""
        errors: dict[str, str] = {}
        if user_input is not None:
            request = user_input.get(CONF_REQUEST, "")
            street = user_input.get(CONF_STREET, "")
            if not request.strip() and not street.strip():
                return await self._address_done(None)
            errors, credentials, street, houses = await validate_request(
                request, street
            )
            if not errors:
                self._credentials, self._street, self._houses = (
                    credentials,
                    street,
                    houses,
                )
                return await self.async_step_house()

        defaults = user_input or {CONF_STREET: self._address_defaults.get(CONF_STREET)}
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="address",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_REQUEST): REQUEST_SELECTOR,
                    vol.Optional(
                        CONF_STREET,
                        description={"suggested_value": defaults.get(CONF_STREET)},
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_house(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Select the house of the street."""
        if user_input is not None:
            return await self._address_done(
                {
                    CONF_STREET: self._street,
                    CONF_HOUSE: user_input[CONF_HOUSE],
                    CONF_CSRF_COOKIE: self._credentials.cookie,
                    CONF_CSRF_TOKEN: self._credentials.token,
                }
            )

        house = self._address_defaults.get(CONF_HOUSE)
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="house",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOUSE,
                        default=house if house in self._houses else vol.UNDEFINED,
                    ): SelectSelector(
                        SelectSelectorConfig(options=self._houses, sort=False)
                    ),
                }
            ),
            description_placeholders={"street": self._street},
        )


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


class IntegrationConfigFlow(AddressFlowMixin, ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Svitlo Yeah: Kyiv, DTEK Kyiv grids, a group."""

    VERSION = 1  # Config entry version for migration handling

    def __init__(self) -> None:
        """Initialize config flow."""
        self.api_yasno = YasnoApi()
        self.data: dict[str, Any] = {}
        self._address_defaults = {}

    async def _address_done(self, address: dict[str, str] | None) -> ConfigFlowResult:
        """Create the entry, with the address or without it."""
        # noinspection PyTypeChecker
        return self.async_create_entry(
            title=NAME, data={**self.data, **(address or {})}
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Ask for a new CSRF pair: the DTEK website rejects the saved one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Paste a new request of the address form of the DTEK website."""
        entry = self._get_reauth_entry()
        street = entry.data.get(CONF_STREET)
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, credentials, _, houses = await validate_request(
                user_input.get(CONF_REQUEST, ""), street
            )
            if not errors and entry.data.get(CONF_HOUSE) not in houses:
                errors = {"base": "house_not_found"}
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CSRF_COOKIE: credentials.cookie,
                        CONF_CSRF_TOKEN: credentials.token,
                    },
                )

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_REQUEST): REQUEST_SELECTOR}),
            errors=errors,
            description_placeholders={
                "street": str(street),
                "house": str(entry.data.get(CONF_HOUSE)),
            },
        )

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
            return await self.async_step_address()

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


class IntegrationOptionsFlow(AddressFlowMixin, OptionsFlow):
    """Handle options flow for Svitlo Yeah."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._address_defaults = config_entry.data

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Show the menu: settings, the address of the DTEK website, its removal."""
        menu = ["settings", "address"]
        if self._config_entry.data.get(CONF_HOUSE):
            menu.append("remove_address")
        # noinspection PyTypeChecker
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def _address_done(self, address: dict[str, str] | None) -> ConfigFlowResult:
        """Save the address in the entry data (reloads the entry)."""
        if address is not None:
            self.hass.config_entries.async_update_entry(
                self._config_entry, data={**self._config_entry.data, **address}
            )
        return self.async_create_entry(title="", data=dict(self._config_entry.options))

    async def async_step_remove_address(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Stop tracking the address."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={
                    k: v
                    for k, v in self._config_entry.data.items()
                    if k not in ADDRESS_KEYS
                },
            )
            return self.async_create_entry(
                title="", data=dict(self._config_entry.options)
            )
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="remove_address",
            description_placeholders={
                "street": str(self._config_entry.data.get(CONF_STREET)),
                "house": str(self._config_entry.data.get(CONF_HOUSE)),
            },
        )

    async def async_step_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="settings",
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
