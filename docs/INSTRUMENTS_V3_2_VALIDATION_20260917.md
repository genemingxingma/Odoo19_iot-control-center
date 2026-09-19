# Washer Pump and Loading Candidate - 2026-09-17

Historical 3.0.2 evidence. The one-second hold control and pump percentages below
are superseded by [the 3.0.3 candidate](INSTRUMENTS_V3_3_VALIDATION_20260917.md),
following the user's balanced-loading and original-motor-value clarification.

Development candidate `3.0.2-dev` / `30002`, Odoo `19.0.2.1.0`.
No production deployment, real-device control, flashing or Git push was performed.
The original supplied archive is unchanged.

## Scope

- Fill A/B: the selected inlet is fully on, bottom drain is off, overflow is
  60% PWM (153/255). Both inlet and overflow stop when filling time expires.
- Drain: both independent pump drivers receive the same duty. The ordinary drain
  retains the legacy 150/255 setting; no new ordinary-drain percentage was inferred.
- Spin dry: both pumps use 50% PWM (128/255), not the legacy raw value 50/255.
- Wait, wash, positioning, idle and fault: pumps off. The old five-second
  post-fill overflow tail is removed; fill positioning/return remain.
- GPIO27 bottom drain / GPIO26 overflow is inferred from the original code's
  C-pump use during filling, not verified against the actual hoses and drivers.
- Manual waits never time out into continuation. Their legacy duration field is
  hidden in Odoo and excluded from active-runtime limits in both validators.
  A local Continue action and a stopped motor are required to leave the wait.
- Six loading positions are spaced at 60 degrees. Absolute rounding avoids
  cumulative error with 3200 steps/revolution. A separate loading-zero offset
  is required; the shorter direction is chosen.
- Selecting a slot does not move. Holding the separate movement button allows
  a low-speed jog, capped at one second per press; release requests forceStop.
  Repeated press packets cannot renew the cap. A new jog requires release/repress.
  Continue is blocked during motion. Slot selections are retained as waiting logs.
- The open-top machine has no lid switch. Explicit commissioned open-rotor mode
  replaces the previous assumed mandatory lid switch and never fabricates a
  closed-lid report. Actual interlocked hardware remains optionally supported.
- Loading is disabled without successful homing, loading calibration and a
  bounded configured jog speed. No production configuration was provisioned.

## Verification

| Check | Result |
| --- | --- |
| Host C++ control tests | 136 checks passed |
| Host TJC rendering/touch tests | 54 checks passed |
| Python core/package regression suite | 32 tests passed |
| PlatformIO ESP8266 / ESP32 builds | Both passed |
| Native Odoo isolated test database | 90 post-tests, 0 failed, 0 errors |
| Translation synchronization | 994 source terms, four catalogs passed |
| Python compileall / git diff whitespace check | Passed; Git CRLF normalization warnings only |

Native host: `imytestlan`, synthetic database `iot_instruments_9661f2bec9fb`.
Test artifact directory: `/tmp/iot_instruments_9661f2bec9fb`.
Native summary timestamp: `2026-09-17 08:20:18 UTC`.
The module's 114 test-stat entries include setup/fixture accounting; this is not
114 distinct post-tests. No running production Odoo service or database changed.

Generated command fixtures are at
`deploy/artifacts/instrument-screen-commands.txt` and its `.loading.txt` companion.
These tests exercise the actual C++ renderer and touch parser, not physical
touchscreen behavior. This turn did not repeat official HMI simulator visual
acceptance. The existing thin HMI transport project/TFT is unchanged; the new
loading page is rendered by ESP32 firmware.

## Build Identity

| Board | BIN bytes | RAM bytes | Program flash bytes |
| --- | ---: | ---: | ---: |
| Heater | 462832 | 31524 | 458683 |
| Washer | 1083696 | 53828 | 1077121 |

SHA-256, from `firmware/instruments/.pio/build/<board>/firmware.bin`:

```text
heater  6356C88FBACF8048DE65FDE6794B5CBA722CB2B6808FB37CE1CC41E1BDF2AED2
washer  B5C594E07BFEF7C92A0EED95287EA90D94CED3908CACEE12D2AB84301E2D07CF
```

## Outstanding Acceptance

This is not a flash-ready safety acceptance. Verify actual pump mapping, 60% and
50% startup/flow, zero and six-slot alignment, driver steps/revolution, jog speed,
stopping distance, release/lost-release handling, screen disconnects and physical
emergency stopping. Open-loop step counts cannot detect a stall or manual rotor
movement. An open rotor has no hand-presence interlock; software and its one-second
window are not a safety-rated stop or a substitute for physical protection.

Earlier backlog remains explicit: boot homing followed by 80% drainage for 20s,
multiple locally stored programs, cycle-count-based washing, actual heater board
identification, hardware OTA/SD validation and expanded offline log capacity.
See [commissioning instructions](INSTRUMENTS_V3_COMMISSIONING.md).
