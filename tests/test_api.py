"""Tests for the WiNet client.

The interesting behaviour is all in how writes are made safe on top of an API
that only offers non-idempotent single steps and a stateless toggle.
"""

from __future__ import annotations

import pytest

from .conftest import api, const


class _FakeClock:
    """Stands in for the time module, handing out a scripted clock."""

    def __init__(self, ticks: list[float]) -> None:
        self._ticks = iter(ticks)
        self._last = 0.0

    def monotonic(self) -> float:
        """Return the next scripted reading, then hold at the last one."""
        try:
            self._last = next(self._ticks)
        except StopIteration:
            pass
        return self._last


async def test_poll_reads_runtime_and_status_only(client, inverter):
    """The fast path returns the snapshot and status, and skips parameters.

    Parameter reads cost the module a round trip to the inverter, so they must
    not ride along on every poll.
    """
    data = await client.async_get_data()

    assert data["runtime"]["standBy"] == 0
    assert data["status"]["fwVer"] == "0.17"
    assert "params" not in data
    assert not any(
        (payload or {}).get("key") == const.KEY_READ_USER_PARAM
        for _, payload in inverter.calls
    )


async def test_read_params_returns_requested_indices(client, inverter):
    """Parameters are read on their own, when asked for."""
    assert await client.async_read_params((0, 4)) == {0: 35, 4: 15}


async def test_status_failure_does_not_fail_the_poll(client, inverter, monkeypatch):
    """Status is diagnostics only, so losing it must not break the update."""
    original = inverter.handle

    def _handle(path, data):
        if path.endswith("get-status"):
            raise api.WiNetConnectionError("nope")
        return original(path, data)

    monkeypatch.setattr(inverter, "handle", _handle)

    data = await client.async_get_data()
    assert data["status"] == {}
    assert data["runtime"]["standBy"] == 0


async def test_set_param_converges_upwards(client, inverter):
    """Stepping up reaches the target and writes exactly once per step."""
    reached = await client.async_set_param(0, 40)

    assert reached == 40
    assert inverter.params[0] == 40
    assert inverter.write_count == 5


async def test_set_param_converges_downwards(client, inverter):
    """Stepping down works the same way."""
    reached = await client.async_set_param(0, 32)

    assert reached == 32
    assert inverter.write_count == 3


async def test_set_param_at_target_writes_nothing(client, inverter):
    """Setting the value it already holds must not touch the EEPROM."""
    reached = await client.async_set_param(0, 35)

    assert reached == 35
    assert inverter.write_count == 0


async def test_set_param_stops_when_clamped(client, inverter):
    """A step that stops moving the value ends the loop instead of spinning."""
    inverter.limits[0] = (0, 37)

    reached = await client.async_set_param(0, 60)

    assert reached == 37
    # Two steps land on the limit, the third proves it will not move further.
    assert inverter.write_count == 3


async def test_set_param_respects_the_step_ceiling(client, inverter, monkeypatch):
    """The loop gives up rather than hammering the module forever."""
    monkeypatch.setattr(api, "MAX_CONVERGE_STEPS", 4)

    reached = await client.async_set_param(0, 1000)

    assert reached == 39
    assert inverter.write_count == 4


async def test_set_param_gives_up_when_the_time_budget_runs_out(
    client, inverter, monkeypatch
):
    """A long move stops rather than tying up a service call for minutes.

    Each step costs the inverter over a second, so wall clock runs out well
    before the step ceiling does.
    """
    monkeypatch.setattr(api, "MAX_CONVERGE_SECONDS", 3)
    # Replace the module reference inside api only, so the event loop's own
    # clock is left alone.
    monkeypatch.setattr(api, "time", _FakeClock([0, 0, 1.6, 3.2]))

    reached = await client.async_set_param(0, 45)

    assert reached == 37
    assert inverter.write_count == 2
    # Left somewhere valid, and a second call would continue from there.
    assert inverter.params[0] == 37


async def test_a_move_within_budget_is_unaffected(client, inverter):
    """The budget must not interfere with ordinary short moves."""
    reached = await client.async_set_param(0, 38)

    assert reached == 38


async def test_pressure_bounds_fit_inside_the_step_ceiling(client):
    """The exposed range must be traversable without hitting the step guard."""
    span = (const.PRESSURE_MAX - const.PRESSURE_MIN) / const.PRESSURE_STEP

    assert span <= const.MAX_CONVERGE_STEPS, (
        f"a full traverse needs {span:.0f} steps but the ceiling is "
        f"{const.MAX_CONVERGE_STEPS}"
    )


async def test_write_is_not_replayed_after_a_dropped_reply(client, inverter):
    """A lost write reply must surface, never be retried blindly.

    The step has already been applied on the device, so a retry would move the
    parameter twice. The caller is expected to re-read and reconcile.
    """
    inverter.drop_writes = 1

    with pytest.raises(api.WiNetConnectionError):
        await client.async_set_param(0, 40)

    assert inverter.params[0] == 36


async def test_reconciling_after_a_dropped_reply_lands_on_target(client, inverter):
    """Re-running the convergence after a failure still reaches the target."""
    inverter.drop_writes = 1

    with pytest.raises(api.WiNetConnectionError):
        await client.async_set_param(0, 40)

    reached = await client.async_set_param(0, 40)

    assert reached == 40
    assert inverter.params[0] == 40


async def test_reads_are_retried_once(client, inverter):
    """A dropped read is safe to repeat, so it is."""
    inverter.fail_next = 1

    assert await client.async_read_params((0,)) == {0: 35}


async def test_read_gives_up_after_the_retry(client, inverter):
    """Two failures in a row propagate."""
    inverter.fail_next = 2

    with pytest.raises(api.WiNetConnectionError):
        await client.async_read_params((0,))


async def test_standby_toggle_reaches_the_requested_state(client, inverter):
    """Turning stand-by on flips the toggle exactly once."""
    assert inverter.standby is False

    runtime = await client.async_set_standby(True)

    assert runtime["standBy"] == 1
    assert inverter.standby is True
    assert inverter.write_count == 1


async def test_standby_already_correct_sends_no_toggle(client, inverter):
    """Asking for the state it is already in must not toggle it."""
    runtime = await client.async_set_standby(False)

    assert runtime["standBy"] == 0
    assert inverter.write_count == 0


async def test_standby_raises_when_it_will_not_take(client, inverter, monkeypatch):
    """If the toggle never sticks, the caller is told rather than misled."""
    original = inverter.handle
    toggles = 0

    def _handle(path, data):
        nonlocal toggles
        if (data or {}).get("key") == const.KEY_TOGGLE_STANDBY:
            # Accepted, but the pump stays where it is.
            toggles += 1
            return {"key": 11, "result": True}
        return original(path, data)

    monkeypatch.setattr(inverter, "handle", _handle)

    with pytest.raises(api.WiNetResponseError):
        await client.async_set_standby(True)

    assert toggles == const.TOGGLE_ATTEMPTS


async def test_bad_runtime_payload_is_rejected(client, inverter, monkeypatch):
    """A truncated snapshot is an error, not silently empty data."""
    monkeypatch.setattr(inverter, "handle", lambda path, data: {"key": 1})

    with pytest.raises(api.WiNetResponseError):
        await client.async_get_data()


async def test_step_reply_for_the_wrong_parameter_is_rejected(
    client, inverter, monkeypatch
):
    """The reply's parIndex is checked, since its key field cannot be trusted."""
    monkeypatch.setattr(
        inverter,
        "handle",
        lambda path, data: (
            {"key": 2, "result": True, "parIndex": 0, "value": 35}
            if path.endswith("get-registers")
            else {"key": 3, "result": True, "parIndex": 9, "value": 36}
        ),
    )

    with pytest.raises(api.WiNetResponseError):
        await client.async_set_param(0, 40)
