"""Delta Solar API client."""
from __future__ import annotations

import logging
from datetime import datetime, date, timezone
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


class DeltaSolarAuthError(Exception):
    pass


class DeltaSolarConnectionError(Exception):
    pass


class DeltaSolarAPI:
    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password

    async def authenticate(self) -> bool:
        """Authenticate and establish a session cookie.

        Tries m_gtop first (session-only login), then app_page fallback.
        """
        # Strategy 1: m_gtop — the mobile top page that initialises the session
        try:
            async with self._session.get(
                LOGIN_URL,
                params={"email": self._email, "password": self._password},
                allow_redirects=True,
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # m_gtop returns the plant list page; any cookie means success
                    if "sec_session_id" in str(self._session.cookie_jar):
                        _LOGGER.debug("Authenticated via m_gtop")
                        return True
        except aiohttp.ClientError as err:
            _LOGGER.debug("m_gtop auth failed: %s", err)

        # Strategy 2: app_page without pid — still sets sec_session_id
        try:
            async with self._session.get(
                APP_PAGE_URL,
                params={
                    "email": self._email,
                    "password": self._password,
                    "lang": "en-us",
                },
                allow_redirects=True,
            ) as resp:
                if resp.status == 200:
                    _LOGGER.debug("Authenticated via app_page")
                    return True
        except aiohttp.ClientError as err:
            _LOGGER.debug("app_page auth failed: %s", err)

        return False

    async def authenticate_with_plant(self, plant_id: str) -> bool:
        """Authenticate using the full plant-specific URL (used by coordinator)."""
        try:
            async with self._session.get(
                APP_PAGE_URL,
                params={
                    "email": self._email,
                    "password": self._password,
                    "p": "energy",
                    "pid": plant_id,
                    "lang": "en-us",
                },
                allow_redirects=True,
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            raise DeltaSolarConnectionError(f"Connection failed: {err}") from err

    async def get_plants(self) -> list[dict[str, Any]]:
        """Return a list of plant dicts from process_init_plant.php."""
        headers = {
            **HEADERS_AJAX,
            "Referer": LOGIN_URL,
        }
        try:
            async with self._session.get(
                INIT_PLANT_URL, headers=headers
            ) as resp:
                if resp.status != 200:
                    raise DeltaSolarAuthError(f"process_init_plant returned {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DeltaSolarConnectionError(f"Cannot reach Delta Solar: {err}") from err

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

        try:
            async with self._session.post(
                AJAX_URL, data=payload, headers=headers
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Energy API returned %s for unit=%s", resp.status, unit)
                    return {}
                raw = await resp.json(content_type=None)
                _LOGGER.debug("Energy response unit=%s: %s", unit, raw)
                return raw if isinstance(raw, dict) else {}
        except aiohttp.ClientError as err:
            raise DeltaSolarConnectionError(f"Energy fetch failed: {err}") from err

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

        The `top` array contains instantaneous AC power readings (W) at
        5-minute UTC intervals aligned to the `ts` millisecond timestamps.
        We find the entry whose timestamp is closest to *now* (UTC).
        """
        if not data:
            return None
        ts_list: list[int] | None = data.get("ts")
        top_list: list[float | None] | None = data.get("top")
        if not ts_list or not top_list or len(ts_list) != len(top_list):
            return None

        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        # Clamp to the last available index so we don't look into the future
        closest_idx = min(
            range(len(ts_list)),
            key=lambda i: abs(ts_list[i] - now_ms),
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
        """Return a dict with today/month/year energies (kWh) and current power (W)."""
        return {
            "today": DeltaSolarAPI.parse_day_energy(day_data),
            "month": DeltaSolarAPI.parse_period_energy(month_data),
            "year": DeltaSolarAPI.parse_period_energy(year_data),
            "current_power": DeltaSolarAPI.parse_current_power(day_data),
        }
