"""Delta Solar API client."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

import aiohttp

from .const import LOGIN_URL, APP_PAGE_URL, INIT_PLANT_URL, AJAX_URL

_LOGGER = logging.getLogger(__name__)

HEADERS_AJAX = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://mydeltasolar.deltaww.com",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (2, 4)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class DeltaSolarAuthError(Exception):
    pass


class DeltaSolarConnectionError(Exception):
    pass


class DeltaSolarSessionExpired(Exception):
    """API responded with a session-invalid error (e.g. 'no plant_data')."""


class DeltaSolarAPI:
    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_redirects: bool = True,
    ) -> tuple[int, Any]:
        """HTTP request with retry/backoff. Returns (status, parsed_body_or_text).

        Retries on transient network errors and 5xx responses with exponential
        backoff. Raises DeltaSolarConnectionError if all attempts fail.
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                    allow_redirects=allow_redirects,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    status = resp.status
                    if status >= 500 and attempt < MAX_RETRIES - 1:
                        _LOGGER.debug(
                            "Delta API %s returned %s; retry %d/%d in %ds",
                            method, status, attempt + 1, MAX_RETRIES,
                            RETRY_BACKOFF_SECONDS[attempt],
                        )
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                        continue
                    try:
                        body: Any = await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        body = await resp.text()
                    return status, body
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_exc = err
                if attempt < MAX_RETRIES - 1:
                    _LOGGER.debug(
                        "Delta API %s failed (%s); retry %d/%d in %ds",
                        method, type(err).__name__, attempt + 1, MAX_RETRIES,
                        RETRY_BACKOFF_SECONDS[attempt],
                    )
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                    continue
        raise DeltaSolarConnectionError(
            f"{method} request failed after {MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc

    async def authenticate(self) -> bool:
        """Authenticate and establish a session cookie.

        Tries m_gtop first (session-only login), then app_page fallback.
        """
        try:
            status, _ = await self._request(
                "GET",
                LOGIN_URL,
                params={"email": self._email, "password": self._password},
            )
            if status == 200 and "sec_session_id" in str(self._session.cookie_jar):
                _LOGGER.debug("Authenticated via m_gtop")
                return True
        except DeltaSolarConnectionError as err:
            _LOGGER.debug("m_gtop auth failed: %s", err)

        try:
            status, _ = await self._request(
                "GET",
                APP_PAGE_URL,
                params={
                    "email": self._email,
                    "password": self._password,
                    "lang": "en-us",
                },
            )
            if status == 200:
                _LOGGER.debug("Authenticated via app_page")
                return True
        except DeltaSolarConnectionError as err:
            _LOGGER.debug("app_page auth failed: %s", err)

        return False

    async def authenticate_with_plant(self, plant_id: str) -> bool:
        """Authenticate using the full plant-specific URL (used by coordinator)."""
        status, _ = await self._request(
            "GET",
            APP_PAGE_URL,
            params={
                "email": self._email,
                "password": self._password,
                "p": "energy",
                "pid": plant_id,
                "lang": "en-us",
            },
        )
        return status == 200

    async def get_plants(self) -> list[dict[str, Any]]:
        """Return a list of plant dicts from process_init_plant.php."""
        headers = {
            **HEADERS_AJAX,
            "Referer": LOGIN_URL,
        }
        status, data = await self._request(
            "GET", INIT_PLANT_URL, headers=headers,
        )
        if status != 200:
            raise DeltaSolarAuthError(f"process_init_plant returned {status}")
        if not isinstance(data, dict):
            raise DeltaSolarAuthError(
                f"process_init_plant returned non-JSON ({type(data).__name__})"
            )

        _LOGGER.debug("process_init_plant response: %s", data)

        plant_ids: list[int] = data.get("plant_ID", [])
        if not plant_ids:
            raise DeltaSolarAuthError("No plants returned — credentials may be wrong")

        plant_names: list[str] = data.get("plant_name", [])
        start_dates: list[str] = data.get("start_date", [])
        is_dst_list: list[int] = data.get("is_dst", [])
        mtnm_list: list[int] = data.get("mtnm", [])

        p_sn: dict = data.get("P_SN", {})
        p_inv_num: dict = data.get("P_INV_NUM", {})
        p_tz: dict = data.get("P_tz", {})
        p_plant_tz: dict = data.get("P_plant_tz", {})
        p_start_date: dict = data.get("P_start_date", {})
        p_is_inv_plt: dict | None = None
        invtp_arr: dict = data.get("invtp_arr", {})
        p_dc_nfo: dict = data.get("P_dc_nfo", {})

        plants: list[dict[str, Any]] = []
        for idx, pid in enumerate(plant_ids):
            pid_str = str(pid)
            sn_list: list[str] = p_sn.get(pid_str, [])
            sn = sn_list[0] if sn_list else ""
            inv_nums = p_inv_num.get(pid_str, ["1"])
            inv_num = int(inv_nums[0]) if inv_nums else 1
            tz_offset = float(p_tz.get(pid_str, 5.5))
            plt_tz = str(p_plant_tz.get(pid_str, tz_offset))
            raw_start = p_start_date.get(pid_str, "2020-01-01 00:00:00")
            # Extract date part only: "2020-07-12 19:44:55" → "2020-07-12"
            start_date = str(raw_start).split(" ")[0] if " " in str(raw_start) else str(raw_start)

            # Current power from P_dc_nfo: {"SN": [null, power_watts, cid]}
            current_power = None
            if sn in p_dc_nfo:
                dc_entry = p_dc_nfo[sn]
                if isinstance(dc_entry, list) and len(dc_entry) >= 2:
                    try:
                        current_power = float(dc_entry[1]) if dc_entry[1] is not None else None
                    except (TypeError, ValueError):
                        current_power = None

            model = ""
            if pid_str in invtp_arr:
                models = invtp_arr[pid_str]
                model = models[0] if models else ""

            plants.append({
                "plant_id": pid_str,
                "plant_name": plant_names[idx] if idx < len(plant_names) else f"Plant {pid}",
                "start_date": start_date,
                "inverter_sn": sn,
                "inverter_num": inv_num,
                "timezone_offset": tz_offset,
                "plt_timezone": plt_tz,
                "mtnm": mtnm_list[idx] if idx < len(mtnm_list) else 0,
                "is_dst": is_dst_list[idx] if idx < len(is_dst_list) else 0,
                "is_inv": 1,
                "plt_type": 1,
                "inverter_model": model,
                "current_power": current_power,
                "raw": data,
            })

        return plants

    async def get_energy(
        self,
        plant_id: str,
        inverter_sn: str,
        inverter_num: int,
        unit: str,
        when: date,
        timezone_offset: float,
        plt_timezone: str,
        start_date: str,
        mtnm: int,
        plt_type: int,
        is_dst: int,
        is_inv: int,
    ) -> dict[str, Any]:
        """Fetch energy data for unit='day'|'month'|'year'."""
        referer = (
            f"{APP_PAGE_URL}?email={self._email}&password={self._password}"
            f"&p=energy&pid={plant_id}&lang=en-us"
        )
        payload = {
            "item": "energy",
            "unit": unit,
            "sn": inverter_sn,
            "inv_num": inverter_num,
            "year": when.year,
            "month": when.month,
            "day": when.day,
            "is_inv": is_inv,
            "plant_id": plant_id,
            "timezone": timezone_offset,
            "start_date": start_date,
            "plt_type": plt_type,
            "mtnm": mtnm,
            "plt_tz": plt_timezone,
            "is_dst_plt": is_dst,
        }
        headers = {**HEADERS_AJAX, "Referer": referer}

        status, body = await self._request(
            "POST", AJAX_URL, data=payload, headers=headers,
        )
        if status != 200:
            _LOGGER.warning("Energy API returned %s for unit=%s", status, unit)
            return {}
        if not isinstance(body, dict):
            return {}
        # `{'errmsg': 'no plant_data'}` means the PHP session was dropped on
        # the server side and the caller needs to re-authenticate.
        if body.get("errmsg") and "day_energy" not in body and "energy" not in body:
            raise DeltaSolarSessionExpired(str(body.get("errmsg")))
        _LOGGER.debug("Energy response unit=%s: %s", unit, body)
        return body

    @staticmethod
    def parse_day_energy(data: dict[str, Any]) -> float | None:
        """Extract today's energy in kWh from a day-unit response.

        The API returns `day_energy` in Wh (e.g. 30720 Wh → 30.72 kWh).
        `te` is an identical alias also present in the response.
        """
        raw = data.get("day_energy") if data else None
        if raw is None:
            raw = data.get("te") if data else None
        if raw is None:
            return None
        try:
            return round(float(raw) / 1000, 3)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_period_energy(data: dict[str, Any]) -> float | None:
        """Extract total energy in kWh from a month- or year-unit response.

        The API returns an `energy` array in Wh per period slot; null entries
        represent future slots and are skipped.

        Example month: [25000, 26800, ...] Wh → sum / 1000 kWh
        Example year:  [296800, 562800, ..., null, null] Wh
        """
        if not data:
            return None
        energy_list = data.get("energy")
        if not isinstance(energy_list, list):
            return None
        try:
            total_wh = sum(float(v) for v in energy_list if v is not None)
            return round(total_wh / 1000, 3)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_current_power(data: dict[str, Any]) -> float | None:
        """Extract current power output in Watts from a day-unit response.

        Delta's day `ts` values are local chart slots, not normal UTC instants.
        Compare them to the local wall-clock time encoded as epoch milliseconds
        to match entries such as 20:10 local time -> 1777666200000.
        """
        if not data:
            return None

        ts_list: list[int] | None = data.get("ts")
        top_list: list[float | None] | None = data.get("top")
        if not ts_list or not top_list or len(ts_list) != len(top_list):
            return None

        local_now_ms = (
            datetime.now() - datetime(1970, 1, 1)
        ).total_seconds() * 1000

        # The API's last slot tracks roughly the current time during the day.
        # When the inverter shuts down at night it stops appending slots, so
        # local_now_ms drifts past ts[-1].  More than one slot-interval of drift
        # means no active production slot exists — return 0 W.
        slot_ms = (ts_list[1] - ts_list[0]) if len(ts_list) > 1 else 300_000
        if local_now_ms > ts_list[-1] + slot_ms:
            return 0.0

        closest_idx = min(
            range(len(ts_list)),
            key=lambda i: abs(ts_list[i] - local_now_ms),
        )

        try:
            val = top_list[closest_idx]
            return float(val) if val is not None else 0.0
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def parse_all_totals(
        day_data: dict[str, Any],
        month_data: dict[str, Any],
        year_data: dict[str, Any],
    ) -> dict[str, float | None]:
        """Return a dict with energy totals and current power."""
        return {
            "today": DeltaSolarAPI.parse_day_energy(day_data),
            "month": DeltaSolarAPI.parse_period_energy(month_data),
            "year": DeltaSolarAPI.parse_period_energy(year_data),
            "current_power": DeltaSolarAPI.parse_current_power(day_data),
        }
