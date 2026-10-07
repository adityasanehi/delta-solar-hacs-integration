"""DataUpdateCoordinator for Delta Solar."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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

# No new inverter report for this long = disconnected (reports normally every 5-15 min).
STALE_AFTER = timedelta(minutes=45)


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
        self._consecutive_failures = 0
        self._last_ts: int | None = None
        # After a restart, assume stale until the report timestamp actually moves.
        self._last_ts_seen = dt_util.utcnow() - STALE_AFTER - timedelta(seconds=1)
        self._lifetime: float | None = None
        self.dc_string_count = 0
        self.ac_phase_count = 0

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

    def _build_inverter_kwargs(self, today: date) -> dict[str, Any]:
        return {
            "plant_id": self._plant_config[CONF_PLANT_ID],
            "inverter_sn": self._plant_config[CONF_INVERTER_SN],
            "inverter_num": self._plant_config[CONF_INVERTER_NUM],
            "when": today,
            "start_date": self._plant_config[CONF_START_DATE],
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

    async def _fetch_live(
        self, api: DeltaSolarAPI, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            more_data = await api.get_inverter_update(item="more", **kwargs)
        except (DeltaSolarConnectionError, DeltaSolarSessionExpired) as err:
            _LOGGER.warning("Delta live data fetch failed: %s", err)
            return {}
        live = DeltaSolarAPI.parse_live_data(
            more_data,
            kwargs["inverter_sn"],
            kwargs["inverter_num"],
        )
        return self._apply_staleness(live)

    def _apply_staleness(self, live: dict[str, Any]) -> dict[str, Any]:
        """Flag the inverter disconnected when its report timestamp stops moving."""
        ts = live.get("last_ts")
        now = dt_util.utcnow()
        if ts != self._last_ts:
            if self._last_ts is not None:
                self._last_ts_seen = now
            self._last_ts = ts
        stale = ts is None or now - self._last_ts_seen > STALE_AFTER
        # Hold the last online reading: the counter can't move while offline, and the
        # portal's offline value is a different, lower counter.
        if stale:
            live["lifetime_energy"] = self._lifetime
            live = DeltaSolarAPI.zero_stale(live)
            if live.get("current_power") is None and ts is not None:
                live["current_power"] = 0.0
        else:
            self._lifetime = live.get("lifetime_energy")
        live["connection"] = "Disconnected" if stale else "Connected"
        if ts:
            # last_ts is plant-local wall time encoded as UTC; assumes plant tz == HA tz.
            naive = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
            live["last_report"] = naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return live

    async def _fetch_event(self, api: DeltaSolarAPI) -> dict[str, Any]:
        try:
            body = await api.get_events(
                self._plant_config[CONF_PLANT_ID], self._plant_config[CONF_INVERTER_SN]
            )
        except DeltaSolarConnectionError as err:
            _LOGGER.debug("Delta event fetch failed: %s", err)
            return {}
        return DeltaSolarAPI.parse_last_event(body)

    async def _async_update_data(self) -> dict[str, Any]:
        api = self._ensure_api()
        kwargs = self._build_kwargs(self._today())
        inverter_kwargs = self._build_inverter_kwargs(self._today())

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
                return self._handle_failure(err2)
        except DeltaSolarConnectionError as err:
            return self._handle_failure(err)

        live = await self._fetch_live(api, inverter_kwargs)
        live.update(await self._fetch_event(api))
        live.setdefault("lifetime_energy", self._lifetime)
        self.dc_string_count = int(live.get("dc_string_count", 0) or 0)
        self.ac_phase_count = int(live.get("ac_phase_count", 0) or 0)

        self._consecutive_failures = 0
        return {
            "today_energy": totals.get("today"),
            "month_energy": totals.get("month"),
            "year_energy": totals.get("year"),
            **live,
        }

    def _handle_failure(self, err: Exception) -> dict[str, Any]:
        self._consecutive_failures += 1
        if self._consecutive_failures <= 1 and self.data is not None:
            _LOGGER.warning(
                "Delta Solar fetch failed (attempt %d); reusing last known values: %s",
                self._consecutive_failures,
                err,
            )
            return self.data
        raise UpdateFailed(f"Cannot connect to Delta Solar: {err}") from err
