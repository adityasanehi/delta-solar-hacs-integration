"""DataUpdateCoordinator for Delta Solar."""
from __future__ import annotations

import logging
from datetime import timedelta, date
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeltaSolarAPI, DeltaSolarConnectionError
from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
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
)

_LOGGER = logging.getLogger(__name__)


class DeltaSolarCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        email: str,
        password: str,
        plant_config: dict[str, Any],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._email = email
        self._password = password
        self._plant_config = plant_config

    async def _async_update_data(self) -> dict[str, Any]:
        connector = aiohttp.TCPConnector(ssl=True)
        jar = aiohttp.CookieJar(unsafe=True)

        async with aiohttp.ClientSession(connector=connector, cookie_jar=jar) as session:
            api = DeltaSolarAPI(session, self._email, self._password)

            plant_id = self._plant_config[CONF_PLANT_ID]

            try:
                await api.authenticate_with_plant(plant_id)
            except DeltaSolarConnectionError as err:
                raise UpdateFailed(f"Cannot connect to Delta Solar: {err}") from err

            today = date.today()
            kwargs = {
                "plant_id": plant_id,
                "inverter_sn": self._plant_config[CONF_INVERTER_SN],
                "inverter_num": self._plant_config[CONF_INVERTER_NUM],
                "when": today,
                "timezone_offset": self._plant_config[CONF_TIMEZONE_OFFSET],
                "plt_timezone": self._plant_config[CONF_PLT_TIMEZONE],
                "start_date": self._plant_config[CONF_START_DATE],
                "mtnm": self._plant_config[CONF_MTNM],
                "plt_type": self._plant_config[CONF_PLT_TYPE],
                "is_dst": self._plant_config[CONF_IS_DST],
                "is_inv": self._plant_config[CONF_IS_INV],
            }

            try:
                day_data = await api.get_energy(unit="day", **kwargs)
                month_data = await api.get_energy(unit="month", **kwargs)
                year_data = await api.get_energy(unit="year", **kwargs)
            except DeltaSolarConnectionError as err:
                raise UpdateFailed(f"Energy fetch error: {err}") from err

            # parse_all_totals also derives current power from the day ts/top arrays
            totals = DeltaSolarAPI.parse_all_totals(day_data, month_data, year_data)

            return {
                "today_energy": totals.get("today"),
                "month_energy": totals.get("month"),
                "year_energy": totals.get("year"),
                "current_power": totals.get("current_power"),
            }
