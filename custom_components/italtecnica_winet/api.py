"""Async client for the Italtecnica WiNet WiFi module.

The module exposes the inverter over a tiny HTTP API. Two quirks drive the shape
of this client:

* There is no "set value" call. Parameters only move one step at a time via the
  increment/decrement keys, exactly like the +/- buttons on the inverter panel.
  Each step returns the resulting value, so writes are done as a convergence
  loop rather than a blind retry -- increments are not idempotent and replaying
  one after a timeout would apply it twice.
* Run/stand-by is a toggle and its response carries no state, so the caller has
  to read the runtime snapshot back to find out where it landed.

Every exchange with the module is serialised behind a single lock. Multi-step
writes hold that lock for their whole duration so nothing interleaves with them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    DEFAULT_TIMEOUT,
    KEY_DEC_USER_PARAM,
    KEY_INC_USER_PARAM,
    KEY_READ_USER_PARAM,
    KEY_RUNTIME,
    KEY_TOGGLE_STANDBY,
    MAX_CONVERGE_SECONDS,
    MAX_CONVERGE_STEPS,
    PARAM_TIMEOUT,
    RETRY_DELAY,
    STEP_DELAY,
    TOGGLE_ATTEMPTS,
    TOGGLE_SETTLE,
)

_LOGGER = logging.getLogger(__name__)

_GET_REGISTERS = "/ajax/get-registers"
_SET_REGISTERS = "/ajax/set-registers"
_GET_STATUS = "/ajax/get-status"


class WiNetError(Exception):
    """Base error for the WiNet module."""


class WiNetConnectionError(WiNetError):
    """The module could not be reached."""


class WiNetResponseError(WiNetError):
    """The module returned something unusable."""


class WiNetClient:
    """Talks to one WiNet module."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the client."""
        self._host = host
        self._base = f"http://{host}"
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()

    @property
    def host(self) -> str:
        """Return the module's host."""
        return self._host

    async def _request(
        self,
        path: str,
        data: dict[str, str] | None = None,
        *,
        idempotent: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform one exchange. Callers must already hold the lock.

        Reads are retried once, because the module happily drops a pooled
        connection and aiohttp only finds out when it writes to it. Writes are
        never retried: an increment that may already have been applied must not
        be replayed, so the caller re-reads and reconciles instead.
        """
        attempts = 2 if idempotent else 1

        for attempt in range(attempts):
            try:
                return await self._request_once(path, data, timeout)
            except WiNetConnectionError:
                if attempt + 1 >= attempts:
                    raise
                _LOGGER.debug("Retrying %s after a dropped connection", path)
                await asyncio.sleep(RETRY_DELAY)

        raise WiNetConnectionError(f"Cannot reach {self._host}")  # pragma: no cover

    async def _request_once(
        self, path: str, data: dict[str, str] | None, timeout: float | None = None
    ) -> dict[str, Any]:
        """Perform exactly one exchange."""
        try:
            async with self._session.post(
                self._base + path,
                data=data,
                timeout=(
                    aiohttp.ClientTimeout(total=timeout) if timeout else self._timeout
                ),
                # The module's httpd advertises keep-alive but recycles sockets
                # on its own schedule; not pooling them avoids the race.
                headers={"Connection": "close"},
            ) as response:
                response.raise_for_status()
                # The module always gzips and mislabels nothing, but it does
                # send an empty body for unsupported keys.
                text = await response.text()
        except asyncio.TimeoutError as err:
            raise WiNetConnectionError(f"Timeout talking to {self._host}") from err
        except aiohttp.ClientError as err:
            raise WiNetConnectionError(f"Cannot reach {self._host}: {err}") from err

        if not text.strip():
            return {}

        try:
            payload = json.loads(text)
        except ValueError as err:
            raise WiNetResponseError(f"Invalid JSON from {self._host}: {text!r}") from err

        if not isinstance(payload, dict):
            raise WiNetResponseError(f"Unexpected payload from {self._host}: {payload!r}")
        return payload

    async def _runtime(self) -> dict[str, Any]:
        """Read the runtime snapshot. Callers must hold the lock."""
        data = await self._request(_GET_REGISTERS, {"key": KEY_RUNTIME})
        if "standBy" not in data:
            raise WiNetResponseError(f"Runtime snapshot missing fields: {data!r}")
        return data

    async def _read_param(self, index: int) -> int:
        """Read one user parameter's raw value. Callers must hold the lock.

        Slow and occasionally flaky -- see ``async_read_params``.
        """
        data = await self._request(
            _GET_REGISTERS,
            {"key": KEY_READ_USER_PARAM, "index": str(index)},
            timeout=PARAM_TIMEOUT,
        )
        if not data.get("result") or "value" not in data:
            raise WiNetResponseError(f"Cannot read parameter {index}: {data!r}")
        return int(data["value"])

    async def _step_param(self, index: int, up: bool) -> int:
        """Nudge a parameter one step and return the resulting raw value.

        The ``key`` field in the reply does not mirror the key that was sent, so
        it is deliberately ignored -- ``parIndex`` and ``value`` are the only
        trustworthy fields.
        """
        key = KEY_INC_USER_PARAM if up else KEY_DEC_USER_PARAM
        data = await self._request(
            _SET_REGISTERS, {"key": key, "index": str(index)}, idempotent=False
        )
        if not data.get("result") or "value" not in data:
            raise WiNetResponseError(f"Step on parameter {index} failed: {data!r}")
        if int(data.get("parIndex", index)) != index:
            raise WiNetResponseError(
                f"Step reply is for parameter {data.get('parIndex')}, expected {index}"
            )
        return int(data["value"])

    async def async_get_data(self) -> dict[str, Any]:
        """Read the runtime snapshot and the module's own status.

        This is the fast path: the snapshot comes back in about 15ms because it
        is a display frame the module already holds. Parameters deliberately are
        not included -- see ``async_read_params``.
        """
        async with self._lock:
            runtime = await self._runtime()
            try:
                status = await self._request(_GET_STATUS)
            except WiNetError:
                # Diagnostics only -- never fail the whole update over it.
                status = {}

        return {"runtime": runtime, "status": status}

    async def async_read_params(self, indices: tuple[int, ...]) -> dict[int, int]:
        """Read stored parameters.

        Each one costs 0.7-2s and can time out, because the module has to fetch
        it from the inverter rather than read it off a cached frame. Call this
        sparingly, not on every poll.
        """
        values: dict[int, int] = {}
        async with self._lock:
            for index in indices:
                values[index] = await self._read_param(index)
        return values

    async def async_set_param(self, index: int, target: int) -> int:
        """Converge a user parameter onto ``target`` and return where it landed.

        Stops early when a step no longer moves the value -- which is how the
        inverter's own clamping shows up -- or when the move runs out of its
        time budget. Either way the parameter is left at a valid value, and
        calling this again picks up from wherever it actually is.
        """
        async with self._lock:
            current = await self._read_param(index)
            steps = 0
            deadline = time.monotonic() + MAX_CONVERGE_SECONDS

            while current != target and steps < MAX_CONVERGE_STEPS:
                if time.monotonic() >= deadline:
                    _LOGGER.warning(
                        "Parameter %s reached %s of %s within %ss; "
                        "set it again to carry on",
                        index,
                        current,
                        target,
                        MAX_CONVERGE_SECONDS,
                    )
                    break

                previous = current
                current = await self._step_param(index, up=target > current)
                steps += 1

                if current == previous:
                    _LOGGER.warning(
                        "Parameter %s stopped at %s before reaching %s; "
                        "the inverter is clamping it",
                        index,
                        current,
                        target,
                    )
                    break

                if current != target:
                    await asyncio.sleep(STEP_DELAY)

            if current != target and steps >= MAX_CONVERGE_STEPS:
                _LOGGER.warning(
                    "Gave up moving parameter %s to %s after %s steps, now at %s",
                    index,
                    target,
                    steps,
                    current,
                )

            return current

    async def async_set_standby(self, standby: bool) -> dict[str, Any]:
        """Drive run/stand-by to the requested state.

        The toggle reply carries no state, so this reads the snapshot back and
        retries rather than assuming the flip took.
        """
        async with self._lock:
            runtime = await self._runtime()

            for _ in range(TOGGLE_ATTEMPTS):
                if bool(runtime["standBy"]) is standby:
                    return runtime

                await self._request(
                    _SET_REGISTERS, {"key": KEY_TOGGLE_STANDBY}, idempotent=False
                )
                await asyncio.sleep(TOGGLE_SETTLE)
                runtime = await self._runtime()

            if bool(runtime["standBy"]) is not standby:
                raise WiNetResponseError(
                    f"Could not put the pump into "
                    f"{'stand-by' if standby else 'run'} after {TOGGLE_ATTEMPTS} attempts"
                )
            return runtime

    async def async_check_connection(self) -> dict[str, Any]:
        """Verify the host really is a WiNet module. Used by the config flow."""
        async with self._lock:
            runtime = await self._runtime()
            try:
                status = await self._request(_GET_STATUS)
            except WiNetError:
                status = {}
        return {"runtime": runtime, "status": status}
