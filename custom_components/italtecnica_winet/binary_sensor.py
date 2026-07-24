"""Binary sensors for the Italtecnica WiNet integration.

These mirror the LEDs on the inverter's own front panel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiNetCoordinator
from .entity import WiNetEntity


@dataclass(frozen=True, kw_only=True)
class WiNetBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a WiNet binary sensor."""

    value_fn: Callable[[WiNetCoordinator], bool | None]


def _flag(field: str) -> Callable[[WiNetCoordinator], bool | None]:
    """Return a reader for one runtime flag."""

    def _read(coordinator: WiNetCoordinator) -> bool | None:
        value = coordinator.runtime.get(field)
        return None if value is None else bool(value)

    return _read


BINARY_SENSORS: tuple[WiNetBinarySensorDescription, ...] = (
    WiNetBinarySensorDescription(
        key="motor_on",
        translation_key="motor_on",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_flag("motorOn"),
    ),
    WiNetBinarySensorDescription(
        key="error",
        translation_key="error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_flag("flagError"),
    ),
    WiNetBinarySensorDescription(
        key="master",
        translation_key="master",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag("master"),
    ),
    WiNetBinarySensorDescription(
        key="double_setpoint",
        translation_key="double_setpoint",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag("doubleSetPoint"),
    ),
    WiNetBinarySensorDescription(
        key="external_enabled",
        translation_key="external_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag("extEnabled"),
    ),
    WiNetBinarySensorDescription(
        key="external_error",
        translation_key="external_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag("extErr"),
    ),
    WiNetBinarySensorDescription(
        key="pilot",
        translation_key="pilot",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_flag("pilota"),
    ),
    WiNetBinarySensorDescription(
        key="manual_mode",
        translation_key="manual_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_flag("pumpMan"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensors."""
    coordinator: WiNetCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WiNetBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class WiNetBinarySensor(WiNetEntity, BinarySensorEntity):
    """One flag from the inverter's runtime snapshot."""

    entity_description: WiNetBinarySensorDescription

    def __init__(
        self, coordinator: WiNetCoordinator, description: WiNetBinarySensorDescription
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the flag's state."""
        return self.entity_description.value_fn(self.coordinator)
