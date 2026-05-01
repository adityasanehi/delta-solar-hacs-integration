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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
