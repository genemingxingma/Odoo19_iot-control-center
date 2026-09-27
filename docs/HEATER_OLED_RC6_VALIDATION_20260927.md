# Heater OLED rc6 validation - 2026-09-27

## Artifact

- Firmware: `3.2.0-rc6` (`32005`).
- Image: 480208 bytes.
- SHA-256: `FD1B9259BF2FDEDF42F0690E80988846FCF757DA571674A92966F65670C49411`.
- Application-only write at `0x000000`; the filesystem was not erased.
- esptool completed the write and verified its data hash.
- esptool software startup succeeded; a subsequent physical reset was captured
  with normal Flash boot mode `(3,7)`.

## Interface verification

The host build and panel tests passed. Runtime diagnostics repeatedly reported
the correct firmware and expected device ID, initialized OLED, mounted storage,
and a healthy journal. The main page uses a large current temperature, a small
state label and target temperature. SW1 shows the complete device ID and IP;
SW3 shows the saved target.

For an uncommissioned device, setup display takes priority over a retained
runtime fault. Fault persistence and the heating permission checks still use
the original fault state. A storage failure still overrides the setup display.

## Outstanding hardware findings

Temperature samples were valid at approximately 24.6-24.8 C, but the startup
enumeration reported zero probes and did not report a detected probe ROM.
This remained true after the physical reset. The strict runtime acceptance
check rejected these samples as an unexpected probe; its result was not
converted into a successful hardware acceptance.

After the physical reset, diagnostics also reported a retained `loop_stalled`
fault. Its trigger has not been determined. No fault reset was performed.

All observed samples reported heating disabled and output off. The device
remains uncommissioned, without platform/Wi-Fi configuration or a saved target.
The OLED initialization and application startup are verified; visual approval
of the physical layout and heating commissioning remain outstanding.

Raw device diagnostics and the protected backup/write receipt are retained
locally outside Git or in the ignored artifact directory. They are not published
in this document.
