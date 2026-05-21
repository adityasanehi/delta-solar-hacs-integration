"""DataUpdateCoordinator for Delta Solar."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DeltaSolarAPI,
    DeltaSolarConnectionError,
    DeltaSolarSessionExpired,
)
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
        self._session: aiohttp.ClientSession | None = None
        self._api: DeltaSolarAPI | None = None
        self._auth_valid = False

    def _ensure_api(self) -> DeltaSolarAPI:
        """Lazily create a persistent session and API client."""
        if self._session is None or self._session.closed:
            self._session = async_create_clientsession(
                self.hass,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
            self._api = DeltaSolarAPI(self._session, self._email, self._password)
            self._auth_valid = False
        assert self._api is not None
        return self._api

    async def _ensure_authenticated(self, api: DeltaSolarAPI) -> None:
        if self._auth_valid:
            return
        plant_id = self._plant_config[CONF_PLANT_ID]
        await api.authenticate_with_plant(plant_id)
        # process_init_plant.php primes the PHP session — without it the
        # energy endpoint returns {'errmsg': 'no plant_data'}.
        await api.get_plants()
        self._auth_valid = True

    def _today(self) -> date:
        try:
            offset = float(self._plant_config[CONF_TIMEZONE_OFFSET])
            return datetime.now(timezone(timedelta(hours=offset))).date()
        except (TypeError, ValueError):
            return date.today()

    def _build_kwargs(self, today: date) -> dict[str, Any]:
        return {
            "plant_id": self._plant_config[CONF_PLANT_ID],
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

    async def _fetch_totals(
        self, api: DeltaSolarAPI, kwargs: dict[str, Any]
    ) -> dict[str, float | None]:
        day_data = await api.get_energy(unit="day", **kwargs)
        month_data = await api.get_energy(unit="month", **kwargs)
        year_data = await api.get_energy(unit="year", **kwargs)
        return DeltaSolarAPI.parse_all_totals(day_data, month_data, year_data)

    async def _async_update_data(self) -> dict[str, Any]:
        api = self._ensure_api()
        kwargs = self._build_kwargs(self._today())

        try:
            await self._ensure_authenticated(api)
            totals = await self._fetch_totals(api, kwargs)
        except DeltaSolarSessionExpired as err:
            # Server dropped our PHP session; re-auth once and retry.
            _LOGGER.debug("Delta session expired (%s); re-authenticating", err)
            self._auth_valid = False
            try:
                await self._ensure_authenticated(api)
                totals = await self._fetch_totals(api, kwargs)
            except (DeltaSolarConnectionError, DeltaSolarSessionExpired) as err2:
                return self._fallback(err2)
        except DeltaSolarConnectionError as err:
            return self._fallback(err)

        return {
            "today_energy": totals.get("today"),
            "month_energy": totals.get("month"),
            "year_energy": totals.get("year"),
            "current_power": totals.get("current_power"),
        }

    def _fallback(self, err: Exception) -> dict[str, Any]:
        """Keep the sensor available on transient failures by reusing last data."""
        if self.data is not None:
            _LOGGER.warning(
                "Delta Solar fetch failed; reusing last known values: %s", err
            )
            return self.data
        raise UpdateFailed(f"Cannot connect to Delta Solar: {err}") from err
