# Italtecnica WiNet — Home Assistant integration

Local integration for the Italtecnica **Sirio** pump inverter (driving a Wilo
pump) through its **WiNet** WiFi module by Net Software srl.

Local polling only — no cloud, no external dependencies.

## Install

Copy `custom_components/italtecnica_winet/` into your Home Assistant
`config/custom_components/` directory, restart, then add the integration and
enter the module's address (e.g. `10.6.2.100`).

## Entities

| Platform | Entities |
|---|---|
| `sensor` | pressure, active set-point, current, voltage, frequency, board and IGBT temperature, hours powered, hours running, starts, active error, WiFi signal |
| `binary_sensor` | motor, error, master, second set-point, external enable, external error, pilot pump, manual mode |
| `switch` | run / stand-by |
| `number` | pressure set-point, pressure set-point 2 |

The active error sensor carries the inverter's error history as attributes —
how many times each of E0–E13 has occurred.

Pressure entities follow the inverter's own bar/psi setting.

## How writes work

The module has **no "set value" call**. Parameters only move one step at a time,
exactly like the +/- buttons on the inverter's panel, and run/stand-by is a
toggle whose reply carries no state. Two consequences shape the client:

* **Writes are a convergence loop, never a blind retry.** Each step returns the
  resulting value, so a lost reply is reconciled by re-reading rather than by
  replaying an increment that may already have been applied. The loop also stops
  as soon as a step no longer moves the value, which is how the inverter's own
  clamping shows up.
* **Every exchange is serialised** behind one lock, and multi-step writes hold
  it for their whole duration.

Each step is very likely an EEPROM write on the inverter, so the number entities
are meant for occasional changes — do not drive them from a continuous control
loop.

### Set-point range and how long a move takes

A step costs the inverter **about 1.6 s**, so wall clock — not the step count —
is what bounds a move. Changing the set-point by 1 bar takes roughly 16 s.

The exposed range is **1.5–6.0 bar**, grounded in this inverter's own
configuration rather than picked arbitrarily: overpressure protection
(parameter 0.3) trips at 10.0 bar, and dry-running protection (0.2) sits at
0.5 bar with a 1.0 bar start delta (0.1). The floor is that delta above
dry-running; the ceiling stays well clear of the trip point.

A move also gives up after **45 s** rather than tying up a service call for
minutes. Stopping short is safe: the set-point is left at a valid intermediate
pressure, and setting it again carries on from wherever it actually is, because
the loop re-reads the real value first. Both bounds live in
[`const.py`](custom_components/italtecnica_winet/const.py) and are a one line
change — but a wider range means slower moves.

## Polling

Measured against a live module:

| Call | Median | Notes |
|---|---|---|
| runtime snapshot (`key=001`) | **15 ms** | rock solid |
| module status | 42 ms | |
| parameter read (`key=002`) | **0.7–1.9 s** | occasionally times out |

The snapshot is a display frame the module already holds; a parameter read makes
it go and fetch the value from the inverter. So the coordinator polls the
snapshot every cycle (5 s by default, configurable in the integration's options)
and treats parameters as a cache: refreshed every 5 minutes, and updated
straight from the reply whenever a write moves one.

Putting parameter reads back on the fast path would cost seconds per poll —
`tests/test_live.py::test_polling_is_fast_enough_for_the_scan_interval` guards
against that.

## Tests

```bash
python3 -m pytest                 # unit tests, no hardware needed
```

The unit tests run the real client against a fake inverter that models the
awkward parts: single-step clamping parameters, a stateless toggle, and dropped
replies.

```bash
WINET_HOST=10.6.2.100 python3 -m pytest tests/test_live.py -v
```

Live tests are skipped unless `WINET_HOST` is set. **They write to a real
pump.** Every write is a round trip that restores the original value, the
restore retries if the module drops a request, and the stand-by test skips
itself while the motor is running. Read them before pointing them at a pump you
care about.

## Protocol

The module's HTTP API is documented in [doc/API.md](doc/API.md), reverse
engineered from its web UI and verified against the device.

Security note: the module has a PIN, but it only guards the advanced parameters.
Reading, changing the set-point and stopping the pump all work **unauthenticated**
over plain HTTP. Keep it on an isolated IoT VLAN.

## License

MIT — see [LICENSE](LICENSE).
