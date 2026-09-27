# TJC8048X550_011C interface

Target: TJC8048X550_011C, 800 x 480 landscape, GB2312, edited and compiled with
USART HMI 1.68.1. The washer interface is English-only. Font 0 preserves the
original GB2312 resource for rollback; font 1 is the 24-pixel antialiased
Verdana Bold resource used by the redesigned interface.

## Native V4 RC4 release candidate

`washer-native-v4.HMI` is the source project and `washer-native-v4.tft` is its
official editor output. The 2026-09-22 RC4 build completed successfully; the TFT
size is 1,753,064 bytes. The source also reopens in USART HMI 1.68.1 without
minimum-width dialogs.

RC4 SHA-256: HMI source
`695bac1230d7619e257aa7046f8236960921edadca44333a48b989cc4423effe`;
production TFT
`c5deeed6b1c13267c1ecaf991cc5427d0a01c73858562c6de99537c5837199b9`;
controller application
`1771a1d92e0bc420746b83d9bc0c918058d96c231ef14f06ebe6df69cea577c5`.

The RC3 TFT and matching `3.6.0-rc3` controller were installed as a matched pair
on 2026-09-22 after a fresh verified 4 MB backup. A bounded paired boot check
confirmed the firmware, V4 screen
handshake, preserved local programs/settings, healthy storage and all outputs off.
RC4 was installed as a matched controller/screen pair on 2026-09-22 after a new
verified 4 MB backup. The screen acknowledged every byte and emitted two V4
heartbeats. A bounded paired boot reported `3.6.0-rc4`, `screen_ready=true`, the
three local programs and device-local pump settings intact, and automatic
preparation already draining at 8.9 seconds. Actuator power was isolated. The
controller was returned to ROM after verification; power-cycle it only when the
actuator supply and machine are ready for supervised automatic preparation.

V4 uses native screen widgets instead of controller-drawn pages or global touch
coordinates. It provides dedicated pages for boot, home, settings, program
selection, automatic startup status, ready, running, chip loading, Wi-Fi, fill times,
maintenance, fault, completion and SD update, plus the editor keyboard pages.
The screen sends explicit `UI|...` actions and the controller owns all safety
checks, state transitions and live field updates.

`page-init.txt` sends `UI|BOOT|4`; timer tm1 sends the `UI|HELLO|4` heartbeat in
`heartbeat.txt` every 400 ms. The matching ESP32 release candidate is
`3.6.0-rc4` (build 30604). Native-screen capability gating prevents an old or
mismatched screen from enabling machine operation. A screen restart during a
run stops the run and never resumes motion automatically.

At power-on, RC4 presents the initialization page as soon as the V4 screen is
paired and starts preparation after the short screen-settle guard. It no longer
shows Home first or inserts the previous ten-second startup delay. The rotor home
operation still has its independent ten-second fault timeout, followed by both
drain pumps for 20 seconds. There is no Prepare, Initialize, Lock or Unlock
button. STOP cancels startup preparation for that power cycle.

Routine subpages use the blue title bar as Back. Wi-Fi and Fill Times return to
Settings, SD Update returns to Maintenance, and other subpages return to Home.
Completion uses its title bar as Home. Redundant bottom Back/Cancel buttons were
deleted; the remaining primary actions occupy the full row. The compiled TFT
contains no obsolete `UI|PREPARE` action.

Wi-Fi credentials and per-device A/B fill times are edited locally and stored
by the ESP32. The program list is selected on the device but remains owned by
the IoT platform; a successful sync replaces the local catalog, while a failed
sync leaves the existing local catalog unchanged. The loading page supports the
calibrated 180/60-degree balanced chip-placement sequence.

Install the V4 RC4 TFT and `3.6.0-rc4` controller firmware as a paired upgrade only.
Do not combine either artifact with the legacy V3 interface. Compiler, protocol,
USB and screen tests are not physical commissioning: motor direction, pump
mapping, fill calibration, drain routing, emergency stop behavior and visible
flicker still require acceptance on the isolated instrument before routine use.

The interaction and safety rationale is documented in
`docs/WASHER_NATIVE_UI_REDESIGN_20260920.md`.
