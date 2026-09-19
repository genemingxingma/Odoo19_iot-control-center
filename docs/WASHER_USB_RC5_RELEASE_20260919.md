# Washer USB and HMI Release Evidence, 2026-09-19

## Released Pair

- Controller: ESP32 4 MB without PSRAM, firmware `3.4.0-rc5` (`30403`).
- Display: TJC8048X550_011C, English-only `washer-v3.tft`.
- Screen source: `firmware/instruments/hmi/washer-v3.HMI`.
- Font resource: `washer_sans_24_bold`, Verdana Bold 24 px, antialiased ASCII.
- Screen palette: deep-blue header, pale-blue background, white information cards
  and blue controls. White controls are not placed on white cards.

The official USART HMI editor compiled the project with zero errors and zero
warnings. The exported TFT is 1,444,392 bytes with SHA-256
`197a8617ee95ae624f9da22bc6561fcee684b4e178006e7ef7b1c0a079ef15d9`.

## USB Flash Evidence

The screen transfer acknowledged all 1,444,392 bytes, then returned to runtime
and emitted a valid V3 heartbeat. The controller was flashed over COM4 and the
application image was independently read back from flash.

- ESP32 application size: 1,114,032 bytes.
- Readback SHA-256:
  `cc54c9169ebc096bcc8dcb2ab809ea8a1ee8a24c86530947bd47dd852d0e3fd3`.
- Reported version after reboot: `3.4.0-rc5`.
- Screen ready: yes.
- Filesystem and journal: healthy.
- Wi-Fi: connected during the bounded test.
- Temperature probe: valid during the bounded test.
- Commissioned: no.
- Platform configured: no.
- Cleanup required: yes.
- Motor and all pump outputs: off.

Actuator power was isolated for the update. This proves paired screen/controller
communication, storage, network and sensor startup, but not motor direction,
pump mapping, fluid volume, emergency stop behavior or loaded mechanical safety.

## Offline Handoff

`tools/prepare_washer_sd.py` prepared `F:\` with the final TFT, USB recovery
images, a signed ESP32 SD package and SHA-256 manifests. The copy was verified
after writing. Device-side SD installation was not exercised in this session.
