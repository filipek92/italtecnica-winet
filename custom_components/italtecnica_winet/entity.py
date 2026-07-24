"""Base entity for the Italtecnica WiNet integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import WiNetCoordinator


class WiNetEntity(CoordinatorEntity[WiNetCoordinator]):
    """Common device wiring for every WiNet entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WiNetCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        host = coordinator.client.host
        self._attr_unique_id = f"{host}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, host)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="Sirio",
            configuration_url=f"http://{host}",
            sw_version=coordinator.status.get("fwVer"),
        )

    @property
    def available(self) -> bool:
        """Return whether the last poll produced a runtime snapshot."""
        return super().available and bool(self.coordinator.runtime)
