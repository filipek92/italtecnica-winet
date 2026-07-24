"""Pressure set-point numbers for the Italtecnica WiNet integration.

The inverter has no "write value" call, so setting a number walks the parameter
up or down one step at a time. The client does that as a convergence loop, which
means a lost reply costs an extra read rather than a doubled increment.

Each step is very likely an EEPROM write on the inverter, so these are meant for
occasional changes -- do not drive them from a continuous control loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WiNetError
from .const import (
    DOMAIN,
    PARAM_PMAX,
    PARAM_PMAX_2,
    PRESSURE_MAX,
    PRESSURE_MIN,
    PRESSURE_STEP,
)
from .coordinator import WiNetCoordinator
from .entity import WiNetEntity


@dataclass(frozen=True, kw_only=True)
class WiNetNumberDescription(NumberEntityDescription):
    """Describes a writable WiNet parameter."""

    param_index: int


NUMBERS: tuple[WiNetNumberDescription, ...] = (
    WiNetNumberDescription(
        key="pressure_setpoint",
        translation_key="pressure_setpoint_1",
        param_index=PARAM_PMAX,
        device_class=NumberDeviceClass.PRESSURE,
        native_min_value=PRESSURE_MIN,
        native_max_value=PRESSURE_MAX,
        native_step=PRESSURE_STEP,
        mode=NumberMode.BOX,
    ),
    WiNetNumberDescription(
        key="pressure_setpoint_2",
        translation_key="pressure_setpoint_2",
        param_index=PARAM_PMAX_2,
        device_class=NumberDeviceClass.PRESSURE,
        native_min_value=PRESSURE_MIN,
        native_max_value=PRESSURE_MAX,
        native_step=PRESSURE_STEP,
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number entities."""
    coordinator: WiNetCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WiNetPressureNumber(coordinator, description) for description in NUMBERS
    )


class WiNetPressureNumber(WiNetEntity, NumberEntity):
    """A pressure parameter that is stepped into place."""

    entity_description: WiNetNumberDescription

    def __init__(
        self, coordinator: WiNetCoordinator, description: WiNetNumberDescription
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the stored set-point."""
        return self.coordinator.pressure(
            self.coordinator.param(self.entity_description.param_index)
        )

    @property
    def native_unit_of_measurement(self) -> str:
        """Return bar or psi, following the inverter's own setting."""
        return "psi" if self.coordinator.is_psi else "bar"

    async def async_set_native_value(self, value: float) -> None:
        """Step the parameter until it reaches the requested pressure."""
        index = self.entity_description.param_index
        target = self.coordinator.to_raw_pressure(value)

        try:
            reached = await self.coordinator.client.async_set_param(index, target)
        except WiNetError as err:
            raise HomeAssistantError(f"Could not set the pressure: {err}") from err

        # The step replies already told us where it landed, so take that rather
        # than paying for another slow parameter read.
        self.coordinator.update_param_cache(index, reached)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

        if reached != target:
            unit = self.native_unit_of_measurement
            raise HomeAssistantError(
                f"The set-point reached {self.coordinator.pressure(reached)} {unit} "
                f"of the requested {value} {unit}. The inverter either clamped it "
                f"or the move ran out of time; setting it again carries on from "
                f"where it is."
            )
