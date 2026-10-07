"""Delta Solar HACS Integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant

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
)
from .coordinator import DeltaSolarCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    plant_config = {
        CONF_PLANT_ID: entry.data[CONF_PLANT_ID],
        CONF_INVERTER_SN: entry.data[CONF_INVERTER_SN],
        CONF_INVERTER_NUM: entry.data[CONF_INVERTER_NUM],
        CONF_TIMEZONE_OFFSET: entry.data[CONF_TIMEZONE_OFFSET],
        CONF_PLT_TIMEZONE: entry.data[CONF_PLT_TIMEZONE],
        CONF_START_DATE: entry.data[CONF_START_DATE],
        CONF_MTNM: entry.data[CONF_MTNM],
        CONF_PLT_TYPE: entry.data[CONF_PLT_TYPE],
        CONF_IS_DST: entry.data[CONF_IS_DST],
        CONF_IS_INV: entry.data[CONF_IS_INV],
    }

    coordinator = DeltaSolarCoordinator(
        hass,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        plant_config=plant_config,
    )

    await coordinator.async_config_entry_first_refresh()

    # Per-string/phase sensors are sized from live data, which is empty at
    # night: remember the last non-zero counts so a night restart keeps them.
    for attr in ("dc_string_count", "ac_phase_count"):
        live = getattr(coordinator, attr)
        if live and entry.data.get(attr) != live:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, attr: live}
            )
        elif not live:
            setattr(coordinator, attr, entry.data.get(attr, 0))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
