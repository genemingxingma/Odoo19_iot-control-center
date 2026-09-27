# Heater rc7 bug fixes and verification - 2026-09-27

## Scope and Confirmed Code Defects

The rc6 USB baseline reported a zero-device startup inventory while addressed
temperature reads were valid. The firmware cached its startup-only inventory
indefinitely. Count and ROM were also obtained from separate search passes.
This did not prove a broken probe. The cause of the first failed bus search was
not established by that baseline alone.

The timer latched `loop_stalled` after a one-second main-loop delay even when
heating was disabled. Persisted faults were restored without distinguishing a
historical latch from a fault triggered in the current boot. Blocking storage
work was not consistently preceded by removing heater power.

## Changes

- Explicitly initialize OneWire GPIO after SDK startup; do not change probe
  resolution or write its EEPROM at boot. Avoid starting ESP8266 Wi-Fi solely
  to read the device identity, and disable Wi-Fi persistence before enabling it.
- Search count and ROM in one bounded pass, retry failed inventory scans, and
  periodically revalidate a healthy probe. Require one CRC-valid DS18B20,
  a valid scratchpad, external power and the configured ROM before commissioning.
  Probe identity is not inferred from a valid temperature reading.
- Latch a new loop fault only while the physical heater output was powered.
  Continue measuring idle latency and report the current-boot trip duration,
  phase and whether a fault was restored. Keep historical fault records latched;
  no protection reset or commissioning is performed by this update.
- Remove power before journal, configuration, probe-scan and HTTPS operations.
  Require a completed new temperature conversion before resuming heat; retain
  timestamped readings for observations instead of invalidating every saved sample.
- Use 42 C with a 600-second / 1 C rise check when no saved target exists.
  Persist acknowledged platform settings and use those offline thereafter.
  Corrupt saved settings fail closed, rather than silently reverting to defaults.
- Use a +/-1 C thermostat band: demand at target minus 1 C, cut off at target
  plus 1 C. This is a switching band, not proof of physical liquid-temperature
  accuracy under every load. Sensor faults stop heating and request a buzzer alarm.
- Save ordinary temperature observations every 3600 seconds. Live heartbeats
  still provide current status and receive settings; they do not create history
  rows. Alarms remain immediate. Offline observations retain the journal retry path.
- Use an external reviewed flash manifest and one serial session for identity,
  full preflash backup, application write/hash verification, data-region hash
  verification and startup. Do not publish real device configuration or backups.

## Artifact and Automated Checks

- Firmware: `3.2.0-rc7`, numeric version `32006`.
- Application: 481664 bytes.
- SHA-256: `83eca74fac996451c3f4a856ee0c5dc5527ab17b8403e5f42372e59e949feed9`.
- RAM: 32888 / 81920 bytes; application code: 477507 / 1044464 bytes.
- Both heater and washer targets compile successfully. The washer is not flashed.
- 95 offline Python tests pass in the existing instrument environment.
- C++ checks: 530 control checks, 34 UI checks, heater panel, probe/loop-guard,
  washer startup, catalog and pump timing tests all pass.
- Probe cases cover failed-first-search recovery, wrong/multiple devices, CRC
  errors, scratchpad errors, parasite-power recovery and bounded scans.
- Loop cases cover idle latency, powered timeout, single latching, clock wrap,
  future timestamp rejection and protection after maintenance.
- Runtime acceptance requires a full minute of matching live samples, periodic
  rescanning, output off, healthy storage/display and no new safety/CRC fault.

## Physical Validation Status

The first 460800-baud backup read failed without a write. The separate 115200-baud
attempt completed a fresh full backup, application write and data-region verification.
Runtime confirmed one matching externally powered, CRC-valid probe, valid
temperature, default target 42 C, periodic rescanning and no new loop fault.

Strict runtime acceptance remained rejected because `journal_healthy=false`.
Read-only inspection of the preflash backup established that all 125 filesystem
blocks were allocated: 116 observations and two critical events. The preflash
fault marker already contained `storage`. This was not a damaged probe or a
filesystem erase caused by the application write. The capacity/legacy-cache
recovery fix is carried forward in rc8; rc7 is not the accepted final release.
The heater load remains disconnected. No production-server update, company
rebinding, Wi-Fi provisioning or protection reset is included in this change.

Network setting delivery, actual hourly uploads, buzzer audibility and thermal
performance still require configured-platform and physical-load acceptance.
Raw evidence and device metadata are retained outside Git or in ignored artifacts.
