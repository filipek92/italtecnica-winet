"""Run/stand-by switch for the Italtecnica WiNet integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WiNetError
from .const import DOMAIN
from .coordinator import WiNetCoordinator
from .entity import WiNetEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch."""
    coordinator: WiNetCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WiNetRunSwitch(coordinator)])


class WiNetRunSwitch(WiNetEntity, SwitchEntity):
    """Puts the pump into run or stand-by.

    The underlying call is a toggle with no confirmation of the resulting state,
    so the client reads the state back and retries; by the time this returns,
    the inverter really is where it was asked to be.
    """

    _attr_translation_key = "run"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: WiNetCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, "run")

    @property
    def is_on(self) -> bool | None:
        """Return True when the pump is in run rather than stand-by."""
        standby = self.coordinator.runtime.get("standBy")
        return None if standby is None else not bool(standby)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Take the pump out of stand-by."""
        await self._async_set(standby=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Put the pump into stand-by."""
        await self._async_set(standby=True)

    async def _async_set(self, standby: bool) -> None:
        """Drive the pump to the requested state and refresh."""
        try:
            await self.coordinator.client.async_set_standby(standby)
        except WiNetError as err:
            raise HomeAssistantError(f"Could not switch the pump: {err}") from err
        await self.coordinator.async_request_refresh()
