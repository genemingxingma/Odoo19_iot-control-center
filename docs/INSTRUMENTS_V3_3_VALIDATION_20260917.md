# Balanced Loading and Original Motor Values - 2026-09-17

Candidate `3.0.3-dev` / `30003`, Odoo `19.0.2.1.0`. Not deployed or flashed.
No real-device controls, production updates or Git push were performed.
The supplied source archive was read, not modified.

## Confirmed Behavior

Each local NEXT tap starts one complete loading-position move, not a one-second
hold-to-jog. From slot 1 the order is `1 -> 4 -> 5 -> 2 -> 3 -> 6 -> 1`.
After initial alignment, all moves use the same direction, alternating +180 and
+60 degrees. Six moves total two revolutions and return to the original position.
The display groups the three opposite pairs in columns; the six indicators are
not arbitrary position buttons and do not claim that slides were loaded.

Entering a manual wait never moves automatically. If not already at the calibrated
initial loading position, ALIGN START explicitly aligns slot 1 first. Only a
stopped motor at the expected pulse-count target advances the sequence. A timeout,
rejected motor command or premature stop does not count as arrival. Further NEXT
taps and Continue are rejected during motion, not queued. STOP aborts the run.
All pumps remain off; finishing an indexing move never resumes washing.

The user's latest instruction supersedes their earlier proposed PWM percentages:

| Phase | Source baseline restored |
| --- | --- |
| Filling | Selected inlet fully on; overflow 255/255; bottom drain off |
| Draining | Both independent drain outputs 150/255, about 58.8% |
| Spin drying | Both drain outputs 50/255, about 19.6%, not 50% |
| Homing and positioning | 1 rev/s, 1 rev/s^2 acceleration |
| New wash / spin steps | 1 / 10 rev/s respectively; existing explicit values unchanged |

Motor constants are centralized in
`firmware/instruments/lib/InstrumentCore/src/motor_profile.hpp`.
Evidence is the supplied original `2.0.2.0/public_var.h` and `2.0.2.0.ino`:
`pump_out_pwm=150`, `pump_dry_pwm=50`, fill overflow `analogWrite(...,255)`,
home/manual position speed 1 rev/s, wash speed 1 rev/s, spin speed 10 rev/s,
and 3200 pulses/revolution. Spindle speed is controlled by STEP/DIR pulses;
no software-controlled spindle supply voltage is claimed.

Full-angle positioning uses the new required `loading_index_hz` configuration,
with 3200 Hz as the original reference. The old one-second `loading_jog_hz`
calibration is deliberately not reused. Missing calibration/configuration still
disables loading motion. No hardware configuration was installed this turn.

Odoo defaults apply to new or type-changed draft steps, preserving explicit speeds
and immutable published programs. Manuals and four translation catalogs were
updated. The loop timestamp is refreshed after serial commands so a fresh screen
heartbeat or Continue cannot look like an unsigned-clock timeout.

## Verification

| Check | Result |
| --- | --- |
| Exact host C++ control core | 524 assertions/checks passed |
| Exact TJC renderer/touch parser | 65 checks passed |
| Python contract and firmware-package regressions | 33 tests passed |
| ESP8266 and ESP32 PlatformIO builds | Both passed |
| Native Odoo post-tests on imytestlan | 91 tests, 0 failed, 0 errors |
| Translation validation | 995 source terms, four catalogs passed |
| Python compileall / Git whitespace check | Passed; normal CRLF warnings only |

Sequence tests cover two complete loading rounds at five calibration offsets,
positive and wrapped positions, cumulative rounding, initial alignment, invalid
configuration, busy/repeated requests, moving/wrong-position completion rejection,
deadline expiry, reset and millis wrap. UI tests cover read-only slot indicators,
press/release matching, disabled motion/Continue controls, stale press rejection,
page changes and immediate STOP on press. They are not a hardware safety test.

Final native database: `iot_instruments_fea777f9059d`.
Artifacts: `/tmp/iot_instruments_fea777f9059d`.
Summary: `2026-09-17 08:51:11 UTC`. The 115 stats entries include fixture accounting;
there are 91 distinct post-tests. An earlier intermediate run also passed 91 tests
but predates the final removal of the proposed 60% overflow setting.

| Board | BIN bytes | RAM bytes | Program flash bytes |
| --- | ---: | ---: | ---: |
| Heater | 462832 | 31524 | 458683 |
| Washer | 1085440 | 53852 | 1078865 |

SHA-256 from `firmware/instruments/.pio/build/<board>/firmware.bin`:

```text
heater  106723DB12787E1C6B1902C88950CD4C03C1FB3B039E044BA241F0500FC5F2CA
washer  4CF984A52AFC77A0F53A2C9EEA118AEDC1C6D8EC668C5120D0914BA8EAA53AD7
```

## Remaining Limits

No physical indexing, pump output, balance, emergency-stop, OTA or SD acceptance
was performed. The unchanged HMI transport/TFT renders this screen through ESP32
commands; this turn did not repeat official simulator visual acceptance.
The original hardware mapping and 3200-pulse calibration require onsite checks.
Pulse counts cannot detect missed steps, manual rotor movement or loaded mass.
A click initiates a full motion and releasing the screen does not stop it; keep
hands clear and independently verify standstill/balance before proceeding.

The other documented backlog remains: boot initialization/drainage, multiple
stored programs, cycle-count washing, heater-board identification and expanded
offline log capacity. See [commissioning](INSTRUMENTS_V3_COMMISSIONING.md).
