"""Delta Solar sensor platform."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_PLANT_ID, CONF_PLANT_NAME, CONF_INVERTER_MODEL, CONF_INVERTER_SN
from .coordinator import DeltaSolarCoordinator


@dataclass(frozen=True)
class DeltaSolarSensorDescription(SensorEntityDescription):
    data_key: str = ""


SENSOR_DESCRIPTIONS: tuple[DeltaSolarSensorDescription, ...] = (
    DeltaSolarSensorDescription(
        key="today_energy",
        data_key="today_energy",
        name="Today's Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    DeltaSolarSensorDescription(
        key="month_energy",
        data_key="month_energy",
        name="Monthly Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
        suggested_display_precision=2,
    ),
    DeltaSolarSensorDescription(
        key="year_energy",
        data_key="year_energy",
        name="Yearly Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sun-wireless",
        suggested_display_precision=2,
    ),
    DeltaSolarSensorDescription(
        key="current_power",
        data_key="current_power",
        name="Current Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        suggested_display_precision=0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeltaSolarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DeltaSolarSensor(coordinator, entry, desc)
        for desc in SENSOR_DESCRIPTIONS
    )


class DeltaSolarSensor(CoordinatorEntity[DeltaSolarCoordinator], SensorEntity):
    entity_description: DeltaSolarSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeltaSolarCoordinator,
        entry: ConfigEntry,
        description: DeltaSolarSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._entry = entry

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.entity_description.data_key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def device_info(self) -> dict[str, Any]:
        plant_name = self._entry.data.get(CONF_PLANT_NAME, "Delta Solar")
        model = self._entry.data.get(CONF_INVERTER_MODEL, "Solar Inverter")
        sn = self._entry.data.get(CONF_INVERTER_SN, "")
        plant_id = self._entry.data.get(CONF_PLANT_ID, "")
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": plant_name,
            "manufacturer": "Delta Electronics",
            "model": model,
            "serial_number": sn,
            "configuration_url": (
                f"https://mydeltasolar.deltaww.com/app_page.php"
                f"?p=energy&pid={plant_id}&lang=en-us"
            ),
        }
