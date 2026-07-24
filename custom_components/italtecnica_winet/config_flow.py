"""Config flow for the Italtecnica WiNet integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WiNetClient, WiNetConnectionError, WiNetError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class WiNetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Italtecnica WiNet."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the module's address and verify it answers."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = WiNetClient(host, session)

            try:
                info = await client.async_check_connection()
            except WiNetConnectionError:
                errors["base"] = "cannot_connect"
            except WiNetError:
                errors["base"] = "invalid_device"
            else:
                network = info.get("status", {}).get("network")
                title = f"Sirio ({network})" if network else f"Sirio ({host})"
                return self.async_create_entry(title=title, data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> WiNetOptionsFlow:
        """Return the options flow."""
        return WiNetOptionsFlow()


class WiNetOptionsFlow(OptionsFlow):
    """Handle the polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=300)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
