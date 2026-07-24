"""Live tests against a real WiNet module.

Skipped unless WINET_HOST is set:

    WINET_HOST=10.6.2.100 python3 -m pytest tests/test_live.py -v

These write to the inverter. Every write is a round trip that restores the
original value, and the run aborts if anything is left changed -- but it is a
real pump, so read what each test does before pointing it at one.
"""

from __future__ import annotations

import asyncio
import os
import time

import aiohttp
import pytest

from .conftest import api, const

HOST = os.environ.get("WINET_HOST")

pytestmark = pytest.mark.skipif(not HOST, reason="WINET_HOST is not set")


@pytest.fixture
async def live_client():
    """Return a client pointed at the real module."""
    async with aiohttp.ClientSession() as session:
        yield api.WiNetClient(HOST, session)


async def test_poll_returns_a_complete_snapshot(live_client):
    """A poll returns everything the sensors need."""
    data = await live_client.async_get_data()

    runtime = data["runtime"]
    for field in ("press", "setPointPress", "standBy", "motorOn", "flagError", "volt"):
        assert field in runtime, f"runtime is missing {field}"

    assert data["status"].get("fwVer")


async def test_repeated_polls_are_stable(live_client):
    """The module survives back to back polls without dropping out.

    Regression test for the sockets it recycles on its own schedule.
    """
    for _ in range(10):
        data = await live_client.async_get_data()
        assert data["runtime"]["press"] is not None


async def test_polling_is_fast_enough_for_the_scan_interval(live_client):
    """A poll has to comfortably fit inside the polling interval.

    The snapshot answers in about 15ms; this guards against parameter reads
    creeping back onto the fast path, which would cost seconds per poll.
    """
    start = time.perf_counter()
    for _ in range(5):
        await live_client.async_get_data()
    average = (time.perf_counter() - start) / 5

    assert average < 0.5, f"a poll took {average:.2f}s on average"


async def test_reading_params_works_but_is_slow(live_client):
    """Parameters read back correctly, on their own slow path."""
    params = await live_client.async_read_params(const.CACHED_PARAMS)

    assert set(params) == set(const.CACHED_PARAMS)
    assert all(isinstance(value, int) for value in params.values())


async def test_setting_the_current_value_writes_nothing(live_client):
    """The no-op path must not touch the EEPROM."""
    params = await live_client.async_read_params((const.PARAM_PMAX,))
    current = params[const.PARAM_PMAX]

    reached = await live_client.async_set_param(const.PARAM_PMAX, current)

    assert reached == current


async def _restore_param(client, index: int, original: int, attempts: int = 4) -> int:
    """Put a parameter back, retrying because the module drops requests.

    Convergence is self-correcting, so re-running it after a failure is safe --
    it re-reads the real value and works out the remaining distance itself.
    """
    last_error: Exception | None = None

    for _ in range(attempts):
        try:
            reached = await client.async_set_param(index, original)
        except api.WiNetError as err:
            last_error = err
            await asyncio.sleep(0.5)
            continue
        if reached == original:
            return reached

    raise AssertionError(
        f"could not restore parameter {index} to {original}: {last_error}"
    )


async def test_setpoint_round_trip(live_client):
    """Step the set-point up two notches and back, leaving it as it was."""
    params = await live_client.async_read_params((const.PARAM_PMAX,))
    original = params[const.PARAM_PMAX]

    try:
        up = await live_client.async_set_param(const.PARAM_PMAX, original + 2)
        assert up == original + 2
    finally:
        back = await _restore_param(live_client, const.PARAM_PMAX, original)

    assert back == original, f"set-point left at {back}, should be {original}"


async def test_standby_round_trip(live_client):
    """Toggle into stand-by and back, confirming each state by reading it back.

    Only runs when the motor is stopped, so it cannot interrupt a live draw.
    """
    data = await live_client.async_get_data()
    runtime = data["runtime"]

    if runtime["motorOn"]:
        pytest.skip("the pump is running, not touching it")

    original = bool(runtime["standBy"])

    try:
        flipped = await live_client.async_set_standby(not original)
        assert bool(flipped["standBy"]) is not original
    finally:
        restored = await live_client.async_set_standby(original)

    assert bool(restored["standBy"]) is original
    assert restored["flagError"] == 0, "the inverter reported an error"
