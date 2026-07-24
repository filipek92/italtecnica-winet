"""Sensors for the Italtecnica WiNet integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ERROR_CODES
from .coordinator import WiNetCoordinator
from .entity import WiNetEntity


@dataclass(frozen=True, kw_only=True)
class WiNetSensorDescription(SensorEntityDescription):
    """Describes a WiNet sensor."""

    value_fn: Callable[[WiNetCoordinator], Any]
    attributes_fn: Callable[[WiNetCoordinator], dict[str, Any]] | None = None


def _active_error(coordinator: WiNetCoordinator) -> str | None:
    """Return the active error, or None when the inverter is healthy."""
    runtime = coordinator.runtime
    if not runtime.get("flagError") or not runtime.get("errorActive"):
        return None
    number = runtime.get("errorNumber")
    return ERROR_CODES.get(number, f"Unknown error {number}")


def _error_history(coordinator: WiNetCoordinator) -> dict[str, Any]:
    """Return how often each error has occurred."""
    runtime = coordinator.runtime
    return {
        ERROR_CODES[code]: runtime.get(f"e{code}", 0)
        for code in ERROR_CODES
        if runtime.get(f"e{code}", 0)
    }


SENSORS: tuple[WiNetSensorDescription, ...] = (
    WiNetSensorDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.pressure(c.runtime.get("press")),
    ),
    WiNetSensorDescription(
        key="pressure_setpoint",
        translation_key="pressure_setpoint",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.pressure(c.runtime.get("setPointPress")),
    ),
    WiNetSensorDescription(
        key="current",
        translation_key="current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: _scaled(c.runtime.get("amp"), 10),
    ),
    WiNetSensorDescription(
        key="max_current",
        translation_key="max_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda c: _scaled(c.runtime.get("ampMax"), 10),
    ),
    WiNetSensorDescription(
        key="voltage",
        translation_key="voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.runtime.get("volt"),
    ),
    WiNetSensorDescription(
        key="frequency",
        translation_key="frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.runtime.get("freq"),
    ),
    WiNetSensorDescription(
        key="max_frequency",
        translation_key="max_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.runtime.get("freqMax"),
    ),
    WiNetSensorDescription(
        key="temperature_board",
        translation_key="temperature_board",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.runtime.get("temp"),
    ),
    WiNetSensorDescription(
        key="temperature_igbt",
        translation_key="temperature_igbt",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.runtime.get("tempIgbt"),
    ),
    WiNetSensorDescription(
        key="hours_powered",
        translation_key="hours_powered",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.runtime.get("hPowerOn"),
    ),
    WiNetSensorDescription(
        key="hours_running",
        translation_key="hours_running",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.runtime.get("hPowerRunning"),
    ),
    WiNetSensorDescription(
        key="starts",
        translation_key="starts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.runtime.get("nrStarts"),
    ),
    WiNetSensorDescription(
        key="active_error",
        translation_key="active_error",
        value_fn=_active_error,
        attributes_fn=_error_history,
    ),
    WiNetSensorDescription(
        key="rssi",
        translation_key="rssi",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.status.get("rssi"),
    ),
)


def _scaled(raw: Any, divisor: int) -> float | None:
    """Scale a raw integer, tolerating a missing field."""
    if raw is None:
        return None
    return round(float(raw) / divisor, 1)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors."""
    coordinator: WiNetCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(WiNetSensor(coordinator, description) for description in SENSORS)


class WiNetSensor(WiNetEntity, SensorEntity):
    """A value read off the inverter."""

    entity_description: WiNetSensorDescription

    def __init__(
        self, coordinator: WiNetCoordinator, description: WiNetSensorDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor's value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, following the inverter's bar/psi setting."""
        if self.entity_description.device_class is SensorDeviceClass.PRESSURE:
            return "psi" if self.coordinator.is_psi else "bar"
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, where the description supplies them."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)
