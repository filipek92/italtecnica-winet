"""Constants for the Italtecnica WiNet integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "italtecnica_winet"

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 5
DEFAULT_TIMEOUT: Final = 10

MANUFACTURER: Final = "Italtecnica"
MODEL: Final = "Sirio (WiNet module)"

# Protocol keys. Sent as zero padded strings, e.g. "001".
KEY_RUNTIME: Final = "001"
KEY_READ_USER_PARAM: Final = "002"
KEY_READ_ADV_PARAM: Final = "003"
KEY_INC_USER_PARAM: Final = "007"
KEY_DEC_USER_PARAM: Final = "008"
KEY_INC_ADV_PARAM: Final = "009"
KEY_DEC_ADV_PARAM: Final = "010"
KEY_TOGGLE_STANDBY: Final = "011"

# User parameter indices, matching the inverter's own menu numbering.
PARAM_PMAX: Final = 0
PARAM_START_DELTA: Final = 1
PARAM_DRY_RUN_PRESSURE: Final = 2
PARAM_PRESSURE_LIMIT: Final = 3
PARAM_PMAX_2: Final = 4
PARAM_STOP_DELTA: Final = 5
PARAM_UNIT: Final = 6
PARAM_IMAX: Final = 10

# Parameters backing the number entities.
CACHED_PARAMS: Final = (PARAM_PMAX, PARAM_PMAX_2)

# Reading a parameter costs 0.7-2s and occasionally times out, because the
# module has to walk the inverter's menu for it -- unlike the runtime snapshot,
# which is a display frame it already holds and answers in ~15ms. So parameters
# are cached, refreshed on this slow interval, and updated straight from the
# reply whenever a write moves them.
PARAM_REFRESH_INTERVAL: Final = 300
PARAM_TIMEOUT: Final = 6

# Guard rails for the increment/decrement convergence loop.
#
# A step costs the inverter about 1.6s, so wall clock is the real constraint,
# not the step count: the budget below is what stops a long move from hanging a
# service call for minutes. Stopping short is safe -- the parameter is left at a
# valid intermediate value, and setting it again carries on from there, because
# the loop re-reads where it actually is.
MAX_CONVERGE_SECONDS: Final = 45
MAX_CONVERGE_STEPS: Final = 50
STEP_DELAY: Final = 0.05
RETRY_DELAY: Final = 0.2
TOGGLE_SETTLE: Final = 0.8
TOGGLE_ATTEMPTS: Final = 3

# Pressure set-point bounds offered to Home Assistant, in bar.
#
# Grounded in the inverter's own configuration rather than picked at random:
# its overpressure protection (parameter 0.3) trips at 10.0 bar and dry-running
# protection (0.2) sits at 0.5 bar with a 1.0 bar start delta (0.1). The floor
# is that delta above dry-running; the ceiling stays well clear of the trip
# point. Widening these is a one line change, but a full traverse costs about
# 1.6s per 0.1 bar, so a wide range means slow moves.
#
# The inverter clamps on its own regardless, and the convergence loop stops as
# soon as a step no longer moves the value.
PRESSURE_MIN: Final = 1.5
PRESSURE_MAX: Final = 6.0
PRESSURE_STEP: Final = 0.1

ERROR_CODES: Final[dict[int, str]] = {
    0: "E0 Low voltage",
    1: "E1 High voltage",
    2: "E2 Short circuit",
    3: "E3 Dry running",
    4: "E4 Ambient temperature",
    5: "E5 Module temperature",
    6: "E6 Overload",
    7: "E7 Out of curve",
    8: "E8 Serial error",
    9: "E9 Pressure limit",
    10: "E10 External error",
    11: "E11 Max starts per hour",
    12: "E12 Error 12V",
    13: "E13 Pressure sensor error",
}
