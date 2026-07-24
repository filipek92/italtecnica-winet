"""Test helpers.

The API client is deliberately free of Home Assistant imports, so it can be
loaded and exercised on its own. These tests do that rather than spinning up a
full Home Assistant test harness.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from typing import Any

import pytest

COMPONENT = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "italtecnica_winet"
)


def _load_client_package() -> types.ModuleType:
    """Load const.py and api.py as a minimal package."""
    package = types.ModuleType("winet")
    package.__path__ = [str(COMPONENT)]
    sys.modules["winet"] = package

    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(
            f"winet.{name}", COMPONENT / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"winet.{name}"] = module
        spec.loader.exec_module(module)

    return sys.modules["winet.api"]


api = _load_client_package()
const = sys.modules["winet.const"]


class FakeInverter:
    """A stand-in for the module's HTTP API.

    Models the two behaviours that matter: parameters only move one step at a
    time and clamp at their limits, and run/stand-by is a toggle whose reply
    carries no state.
    """

    def __init__(
        self,
        params: dict[int, int] | None = None,
        standby: bool = False,
        limits: dict[int, tuple[int, int]] | None = None,
    ) -> None:
        """Set up the fake inverter."""
        self.params = dict(params or {0: 35, 4: 15})
        self.standby = standby
        self.limits = dict(limits or {})
        self.calls: list[tuple[str, dict[str, str] | None]] = []
        self.fail_next: int = 0
        self.drop_writes: int = 0

    def handle(self, path: str, data: dict[str, str] | None) -> dict[str, Any]:
        """Answer one request."""
        self.calls.append((path, data))

        if self.fail_next:
            self.fail_next -= 1
            raise api.WiNetConnectionError("simulated drop")

        key = (data or {}).get("key")

        if path.endswith("get-status"):
            return {"fwVer": "0.17", "rssi": -63, "network": "test"}

        if key == const.KEY_RUNTIME:
            return {
                "key": 1,
                "standBy": int(self.standby),
                "flagError": 0,
                "barOrPsi": 0,
                "motorOn": 0,
                "press": 30,
                "setPointPress": self.params.get(0, 35),
                "errorActive": False,
                "errorNumber": 0,
            }

        if key == const.KEY_READ_USER_PARAM:
            index = int(data["index"])
            if index not in self.params:
                return {}
            return {"key": 2, "result": True, "parIndex": index, "value": self.params[index]}

        if key in (const.KEY_INC_USER_PARAM, const.KEY_DEC_USER_PARAM):
            index = int(data["index"])
            step = 1 if key == const.KEY_INC_USER_PARAM else -1
            low, high = self.limits.get(index, (-10**6, 10**6))
            applied = min(max(self.params[index] + step, low), high)

            if self.drop_writes:
                # The write lands but the reply is lost.
                self.drop_writes -= 1
                self.params[index] = applied
                raise api.WiNetConnectionError("simulated drop after apply")

            self.params[index] = applied
            # The real module returns a key that does not mirror the request.
            return {"key": 3, "result": True, "parIndex": index, "value": applied}

        if key == const.KEY_TOGGLE_STANDBY:
            self.standby = not self.standby
            return {"key": 11, "result": True}

        return {}

    @property
    def write_count(self) -> int:
        """Return how many writes were attempted."""
        return sum(
            1
            for path, data in self.calls
            if path.endswith("set-registers")
            and (data or {}).get("key")
            in (
                const.KEY_INC_USER_PARAM,
                const.KEY_DEC_USER_PARAM,
                const.KEY_TOGGLE_STANDBY,
            )
        )


@pytest.fixture
def inverter() -> FakeInverter:
    """Return a fake inverter."""
    return FakeInverter()


@pytest.fixture
def client(monkeypatch, inverter):
    """Return a client wired to the fake inverter."""
    instance = api.WiNetClient("10.0.0.1", session=None)

    async def _request_once(path, data, timeout=None):
        return inverter.handle(path, data)

    monkeypatch.setattr(instance, "_request_once", _request_once)
    monkeypatch.setattr(const, "STEP_DELAY", 0)
    monkeypatch.setattr(api, "STEP_DELAY", 0)
    monkeypatch.setattr(api, "RETRY_DELAY", 0)
    monkeypatch.setattr(api, "TOGGLE_SETTLE", 0)
    return instance
