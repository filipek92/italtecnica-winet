"""Polling coordinator for the Italtecnica WiNet integration."""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WiNetClient, WiNetError
from .const import CACHED_PARAMS, DOMAIN, PARAM_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


class WiNetCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps one module's runtime snapshot, parameters and status fresh.

    The runtime snapshot is cheap and polled every cycle. Stored parameters are
    not: each costs the module a round trip to the inverter, so they are cached,
    refreshed on a slow interval, and updated straight from the reply whenever a
    write moves one.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: WiNetClient,
        scan_interval: int,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.entry = entry
        self._params: dict[int, int] = {}
        self._params_read_at: float = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the runtime snapshot, and parameters when they are due."""
        try:
            data = await self.client.async_get_data()
        except WiNetError as err:
            raise UpdateFailed(str(err)) from err

        if self._params_due:
            try:
                self._params = await self.client.async_read_params(CACHED_PARAMS)
                self._params_read_at = time.monotonic()
            except WiNetError as err:
                # Slow and flaky by nature; keep serving the cached values
                # rather than dropping the whole update on the floor.
                _LOGGER.debug("Parameter refresh failed, keeping cache: %s", err)

        data["params"] = dict(self._params)
        return data

    @property
    def _params_due(self) -> bool:
        """Return whether the parameter cache needs refreshing."""
        if not self._params:
            return True
        return time.monotonic() - self._params_read_at >= PARAM_REFRESH_INTERVAL

    def update_param_cache(self, index: int, value: int) -> None:
        """Record a parameter's new value after a write moved it."""
        self._params[index] = value
        if self.data is not None:
            self.data["params"] = dict(self._params)

    @property
    def runtime(self) -> dict[str, Any]:
        """Return the latest runtime snapshot."""
        return self.data.get("runtime", {}) if self.data else {}

    @property
    def status(self) -> dict[str, Any]:
        """Return the latest module status."""
        return self.data.get("status", {}) if self.data else {}

    @property
    def is_psi(self) -> bool:
        """Return True when the inverter is configured in PSI rather than bar."""
        return bool(self.runtime.get("barOrPsi"))

    def param(self, index: int) -> int | None:
        """Return a cached parameter's raw value."""
        return self._params.get(index)

    def pressure(self, raw: float | None) -> float | None:
        """Scale a raw pressure reading into the inverter's configured unit."""
        if raw is None:
            return None
        return float(raw) if self.is_psi else round(float(raw) / 10, 1)

    def to_raw_pressure(self, value: float) -> int:
        """Turn a pressure in the configured unit back into a raw value."""
        return int(round(value)) if self.is_psi else int(round(value * 10))
