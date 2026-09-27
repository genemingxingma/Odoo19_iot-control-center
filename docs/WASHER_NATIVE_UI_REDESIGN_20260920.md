# Washer Native UI Redesign

Status: native V4 field-test pair was first flashed on 2026-09-20. The RC3
production TFT and matching `3.6.0-rc3` (build 30603) controller image were
installed as a pair on 2026-09-22 after a fresh verified 4 MB backup. RC4
`3.6.0-rc4` (build 30604) and its paired TFT were installed later the same day
after another verified 4 MB backup. Motor/pump power remained isolated during USB
checks, so this is not
physical actuator commissioning or final visible-flicker acceptance.

## Findings

1. `paint()` runs at least once a second and the previous renderer resent large
   filled rectangles, text and buttons even with identical values. Serial writes
   are deliberately bounded to 128 bytes, so erase and redraw are visible over time.
2. Every touch action marks the view dirty. The previous renderer interpreted
   that as `cls`, including every character entry, backspace and case change.
3. The HMI editor project is a one-page serial canvas, not native operator pages.
   The earlier PNG layout checks cannot prove motion-free, flicker-free interaction.
4. Preparation is hidden under Device Care, while the overview exposes Start.
   Fault reset and firmware updates compete with routine settings. Debug states
   such as FIELD TEST describe an engineering mode rather than what to do next.
5. Pump timing is a calibration parameter but appears as an unexplained setting.
   Saving a number, calibrating delivered volume and actually operating a pump
   must never be presented as the same action.

## Implemented

- Keep a bounded retained scene per page; identical renders send zero bytes.
- Keyboard input changes only its entry field; unchanged keys and background remain.
- Temperature/countdown changes update only their own fields.
- A progress bar resets its background only when its progress changes, including decreases.
- Preserve stale-touch invalidation and immediate STOP handling.
- Reconstruct the screen on explicit reconnect/BOOT. A screen restart during
  a run stops the run rather than hiding the interruption behind a fresh display.
- Host regression: unchanged frame, dirty no-op, backspace, keyboard case,
  temperature-only update, shrinking progress and reconnect. Representative
  full keyboard is 2266 UART bytes; a character deletion is 44 bytes, no `cls`.
- Local official editor compiled the new BOOT event with zero errors/warnings.
  Native pages are now authored and installed; visible hardware behavior still
  requires operator observation with the instrument in front of them.
- Present the initialization page immediately after the V4 screen handshake and
  begin preparation after only the screen-settle guard. The ten-second value is
  retained solely as the rotor-home fault timeout, not as a startup delay.
- Use the title bar consistently as Back or Home. Remove duplicate bottom
  Back/Cancel controls and expand the remaining primary action to a full row.

## Native Page Structure

### Native V4 implementation

`firmware/instruments/hmi/washer-native-v4.HMI` contains native pages for boot,
home, settings, programs, automatic startup status, ready, running, loading, Wi-Fi, pump
timing, maintenance, fault, completion and SD update, plus the editor keyboard
pages. It uses font 1 (24-pixel Verdana Bold), a deep-blue header, light-blue
filled controls and a white content surface. Screen buttons emit explicit
newline-delimited `UI|...` actions; the ESP32 validates all machine state and
safety conditions before accepting them.

The official USART HMI 1.68.1 RC4 compile completed successfully and produced a
1,753,064-byte TFT. The source reopens without minimum-width dialogs.
Obsolete Prepare/navigation buttons are absent from the page object tables and
the compiled TFT contains no `UI|PREPARE` action.

RC4 SHA-256 values:

- HMI source: `695bac1230d7619e257aa7046f8236960921edadca44333a48b989cc4423effe`
- production TFT: `c5deeed6b1c13267c1ecaf991cc5427d0a01c73858562c6de99537c5837199b9`
- ESP32 application: `1771a1d92e0bc420746b83d9bc0c918058d96c231ef14f06ebe6df69cea577c5`

For historical reference, the installed RC2 controller application SHA-256 is
`906becf2ca702ef43bfe06efda59c9f90bd08529fd911587717ff28f6e29e710`.
Two current 4 MB backups were independently read and verified before the rc1
and rc2 writes. The rc2 updater verified its application plus the preserved
prefix and full data region after writing; NVS, Wi-Fi, the local program catalog,
device-specific A/B pump times and journals remained unchanged.

The first paired boot exposed one real integration issue: the screen completed
boot while the controller was deliberately held in ROM, so the controller
missed the screen's one-shot BOOT frame. Rc2 permits the versioned V4 heartbeat
to establish the screen only during the controller's first 30 idle seconds.
BOOT during operation and serial loss retain their fail-safe stop behavior.

Final 30-second diagnostics repeatedly reported `screen_ready=true`, heartbeat
age below 400 ms, Wi-Fi connected, platform catalog HTTP 304, storage and journal
healthy, the saved demo program and A/B 10-second calibration present, and every
enable/pump/motor output off. Evidence is in
`deploy/artifacts/washer-v4-rc2-postflash-status-20260920-195239.json`.

### Target Structure

Use English only, blue/white, native buttons with filled blue/light-blue backgrounds,
the existing bold font, and stable page layouts visible in the USART HMI editor.
The HMI owns layout/navigation/input widgets. The ESP32 owns execution, validation,
settings persistence and all safety gates. A native widget click is a request,
never proof that the controller accepted an action.

| Page | User purpose | Primary actions | Important distinction |
| --- | --- | --- | --- |
| Power-on | See automatic machine preparation | Stop only if unsafe | Show initialization directly after pairing, then home the rotor and drain both outlets for 20 seconds |
| Home | See selected program and readiness | Choose Program, Review and Start, Settings | Show the next required action, not engineering mode |
| Programs | Select a synchronized local program | Select, Back | Selection does not start a run; revision visible |
| Ready | Final check of program and local A/B times | Start Run, Back | Missing configuration links to the relevant setting |
| Running | Know the current physical action | Stop Run | Program, Step N of M, action, cycle, remaining and temperature in fixed positions |
| Load Slides | Load opposing pairs while stopped | Next Position, Continue, Stop Run | Movement and continue requests remain controller-gated; no auto-continue |
| Finished | Know the run is over | Back to Home | Show completion only after rotor stop, not timer expiry |
| Settings | Change routine configuration | Wi-Fi, Fill Times, Back | No movement when merely entering or saving |
| Wi-Fi | Edit connection details | Save and Connect, title-bar Back | Keyboard edits are a draft; show connecting/success/failure distinctly |
| Fill Times | Store measured A/B seconds | Save A + B, title-bar Back | Label Buffer A and Buffer B, allowed range and device-local scope; no automatic pump test |
| Maintenance | Deliberate service actions | Loading Reference, Firmware Update, Fault Details | Not on the routine start path; confirmations explain physical effects |
| Fault | Identify cause and next action | Reset Fault, Details | Reset acknowledges a corrected fault, never resumes the interrupted run |

Rename ambiguous operator terms in the native design:
`DEVICE CARE` -> `Settings` or `Maintenance` according to purpose;
remove `INITIALIZE`, `Prepare Machine`, Lock and Unlock because preparation is automatic at power-on;
`PUMP TIMES` -> `Fill Times` with distinct `Buffer A` and `Buffer B` values;
`USE PROGRAM` -> `Select`; `REVIEW / START` -> a separate review then `Start Run`;
`SET LOADING ZERO` -> `Set Loading Reference` with a stopped-position diagram.
Do not expose `uncommissioned`, RAM, chip type or rotor hardware mode on Home.
Do not remove the underlying physical-test authorization or falsify acceptance.

## Remaining physical acceptance

RC4 source compilation, protocol gating, offline checks and paired
screen/controller flashing are complete; physical checks are not. Before routine operation, reconnect
actuator power under supervision and verify home direction/sensor, both fill
pumps, both drainage pumps, wash direction/reversal, dry speed, STOP behavior,
loading-reference geometry and measured A/B delivered volumes. Obtain a screen
photo or video while typing, navigating and running to confirm the original
flicker complaint is resolved on the actual panel.

The controller remains intentionally uncommissioned. RC4 removes the startup
delay and unifies header navigation, but it does not remove hardware
commissioning, motion authorization, storage integrity or fault gates. A bounded
paired boot check reported firmware `3.6.0-rc4`, `screen_ready=true`, three
preserved local programs, pump-setting revision 2 and healthy storage/journal.
With the home input already active, preparation reached dual drainage by 8.9
seconds, before the former additional ten-second delay could have elapsed. The
isolated logical pump commands were 150/255 and the controller was returned to
ROM immediately after the check. Its next power cycle must be supervised because
automatic preparation will begin promptly, home the rotor and run both drain
pumps.
