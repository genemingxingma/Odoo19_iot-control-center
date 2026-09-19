# Instrument Hardware Clarification Validation - 2026-09-17

Historical 3.0.1 evidence. The pump, manual-wait and rotor-guard assumptions below
are superseded by [the 3.0.2 candidate record](INSTRUMENTS_V3_2_VALIDATION_20260917.md).

Development candidate only: MCU `3.0.1-dev` / `30001`, Odoo `19.0.2.1.0`.
This supersedes the earlier V3 candidate's assumed level inputs and washer
temperature interlocks. No production release, real-device control or flashing
was performed. The supplied source archive remains unchanged.

## Confirmed requirements and implementation

- Neither instrument has liquid-level sensing. The heater no longer requires
  PCF8574 inputs. Its revised candidate identity is `heater-esp8266-v2`.
- Washer programs are authored only in Odoo. The latest accepted program is
  atomically saved in `/recipe.json` and loaded after reboot; local starting
  does not require an online connection. This is one current program, not a
  multi-program library. Interrupted runs never resume automatically.
- Filling and draining use elapsed pump-on time. The logical fill/drain order
  validator is not a level measurement. Actual pump volume/timing needs field
  calibration. The original mechanism's extra 5-second C-drain and return-home
  sequence remains explicit in the firmware.
- Washer temperature is observational: no setpoint, temperature range interlock
  or heating output. Missing probes generate a visible warning and run-log
  events without stopping the timed program. Logs retain measured temperature
  and validity at each recorded event.
- Heater setpoints and protection are downloaded together and saved atomically
  to `/targets.json`; applied acknowledgment follows successful persistence.
  Invalid/missing configuration cannot arm heat. No local temperature editor.
- User-confirmed defaults: 600 seconds of actual heating, rise <= 1 C causes a
  latched fault. Exactly 1 C is a failure, not a pass. Both heating channels stop
  when either probe fails, overheats or fails the rise test.
- Intentional network/output-off intervals are excluded from the heating-time
  counter without clearing accumulated time. Reaching the setpoint clears the
  observation window, so normal thermostat-off time cannot trigger this alarm.
- Faults persist on the device. Sensor recovery, setpoint updates and reboot
  never restart heat. An operator must inspect and deliberately arm locally.
- The platform separates requested targets, device-stored targets, current
  channel alarms and immutable alarm history. Alarm-only events do not add
  temperature samples or distort hourly averages.

## Verification

| Check | Result |
| --- | --- |
| Pure C++ controller/scheduler checks | 73 passed |
| C++ screen parser/render/confirmation checks | 21 passed |
| Python core/contract/package suite | 31 passed |
| Native Odoo IoT module suite | 90 tests, 0 failed, 0 errors |
| Translation check | 993 source terms, 4 catalogs passed |
| ESP8266 and ESP32 cross-compilation | Both passed |
| Python compilation and Git whitespace check | Passed |

Commands: `python tools/test_instrument_core.py`; instrument virtualenv
`python -m unittest discover -s core_tests`; `python tools/instrument_test_lan.py`;
`python -X utf8 tools/check_i18n.py`; instrument virtualenv
`python -m platformio run --project-dir firmware/instruments`.

Native tests used the new synthetic database `iot_instruments_be90204b9548` on
imytestlan. Evidence: `/tmp/iot_instruments_be90204b9548/test.log`, result at
07:52:44 UTC. Actual test count is 90; Odoo's separate 114-entry statistics
include setup accounting. Separate localhost test process, addon/data paths,
no workers/cron and stop-after-init; existing databases/services unchanged.
Test artifacts were retained. The test host's unrelated social-module state
warning remains outside this change's scope.

Boundary checks cover exactly/just before 600 seconds, exactly/above 1 C,
normal thermostat holding, resumed network pauses, setpoint updates preserving
the timer, protection changes rejected during heating, sensor failure/recovery,
latched faults, timer wrap, timed fill/drain transitions, immutable alarm replay,
no duplicate temperature sample for alarms, and washer sensor warnings that
leave the reported run state running.

## Candidate binaries

Heater: `.pio/build/heater/firmware.bin` under `firmware/instruments`, 462,832 bytes.
RAM 31,524 / 81,920; linked flash 458,683 / 1,044,464 bytes.
SHA-256: `00806401DB53EC839190AC794EC4CC74B530F0A5AA27AE7437B323413DB682E4`.

Washer: `.pio/build/washer/firmware.bin` under `firmware/instruments`, 1,080,160 bytes.
RAM 53,804 / 327,680; linked flash 1,073,589 / 1,769,472 bytes.
SHA-256: `A5BA1712141FDC5F4B4908900000DAFF748DEC82CCFD747A31FD42DC32E00740`.

TJC HMI/TFT transport project is unchanged from the earlier verified export;
displayed text is drawn by ESP32. This update did not repeat official-editor
visual acceptance. SDK/dependency warnings remain; builds are not warning-free.

## Remaining limits

- Still requires actual heater board/flash/wiring, driver polarity and probe ROM
  verification. Candidate local button uses GPIO0 after boot; holding it at
  reset can enter programming mode. No hardware mapping is claimed validated.
- Persistence is implemented but physical power-cut/offline-reboot, exact relay
  cutoff latency, OTA and SD interruption acceptance have not been performed.
- Logging remains bounded at 128 queued events; full storage safely stops the
  device. At one sample per minute the heater has about 128 minutes of raw
  temperature backlog, less when alarms are queued. This is NOT unlimited or
  long-duration offline operation. Longer autonomy needs a separately validated
  storage/retention design; no old logs were silently deleted to hide this limit.
- Temperature-rise protection is an anomaly indicator, not proof of an empty
  container and not a substitute for an independent thermal cutoff.
- Washer door/motion hardware and real stop time remain unverified. Native
  tests do not replace real-browser visual or physical instrument acceptance.

See [commissioning checklist](INSTRUMENTS_V3_COMMISSIONING.md).
