"""Config flow for Delta Solar integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .api import DeltaSolarAPI, DeltaSolarAuthError, DeltaSolarConnectionError
from .const import (
    DOMAIN,
    CONF_PLANT_ID,
    CONF_INVERTER_SN,
    CONF_INVERTER_NUM,
    CONF_TIMEZONE_OFFSET,
    CONF_PLT_TIMEZONE,
    CONF_START_DATE,
    CONF_MTNM,
    CONF_PLT_TYPE,
    CONF_IS_DST,
    CONF_IS_INV,
    CONF_PLANT_NAME,
    CONF_INVERTER_MODEL,
)

_LOGGER = logging.getLogger(__name__)


class DeltaSolarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._plants: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            try:
                self._plants = await self._fetch_plants()
            except DeltaSolarAuthError:
                errors["base"] = "invalid_auth"
            except DeltaSolarConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Delta Solar setup")
                errors["base"] = "unknown"

            if not errors:
                if len(self._plants) == 1:
                    return await self.async_step_plant({"plant_id": self._plants[0]["plant_id"]})
                return await self.async_step_plant()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            chosen_id = user_input["plant_id"]
            plant = next(
                (p for p in self._plants if p["plant_id"] == chosen_id), None
            )
            if plant is None:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"delta_solar_{chosen_id}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Delta Solar — {plant['plant_name']}",
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_PLANT_ID: plant["plant_id"],
                        CONF_PLANT_NAME: plant["plant_name"],
                        CONF_INVERTER_SN: plant["inverter_sn"],
                        CONF_INVERTER_NUM: plant["inverter_num"],
                        CONF_TIMEZONE_OFFSET: plant["timezone_offset"],
                        CONF_PLT_TIMEZONE: plant["plt_timezone"],
                        CONF_START_DATE: plant["start_date"],
                        CONF_MTNM: plant["mtnm"],
                        CONF_PLT_TYPE: plant["plt_type"],
                        CONF_IS_DST: plant["is_dst"],
                        CONF_IS_INV: plant["is_inv"],
                        CONF_INVERTER_MODEL: plant["inverter_model"],
                    },
                )

        plant_options = {p["plant_id"]: p["plant_name"] for p in self._plants}
        return self.async_show_form(
            step_id="plant",
            data_schema=vol.Schema(
                {
                    vol.Required("plant_id"): vol.In(plant_options),
                }
            ),
            errors=errors,
        )

    async def _fetch_plants(self) -> list[dict[str, Any]]:
        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            api = DeltaSolarAPI(session, self._email, self._password)
            authed = await api.authenticate()
            if not authed:
                raise DeltaSolarAuthError("Authentication failed")
            return await api.get_plants()
