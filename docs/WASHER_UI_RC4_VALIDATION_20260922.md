# Washer V4 RC4 Validation

RC4 pairs controller `3.6.0-rc4` (build 30604) with the native V4 screen image.
It removes the ten-second startup delay, presents initialization directly after
screen pairing, and standardizes title-bar navigation. The rotor-home operation
retains its separate ten-second fault timeout.

## Operator behavior

- Initialization is the first controller-owned page after the V4 handshake.
- The title bar returns from Programs and Ready to Home; from Wi-Fi, Fill Times
  and Maintenance to Settings; and from SD Update to Maintenance.
- The Finished title returns to Home.
- Redundant bottom Back/Cancel buttons are deleted. STOP and each page's primary
  action remain full-width and send controller commands.
- Fill Times labels the two device-local values as Buffer A and Buffer B.

## Build evidence

- PlatformIO ESP32 washer build succeeded: RAM 54,588 / 327,680 bytes; linked
  flash 1,111,377 / 1,769,472 bytes.
- Native core tests passed: 530 checks.
- Native retained-UI tests passed: 34 checks.
- Heater panel, washer startup and catalog/pump timing tests passed.
- Washer paired-build contract passed: 13 tests.
- USART HMI 1.68.1 compiled the RC4 source successfully.
- HmiSafe verified the TFT header CRC, tail CRC and footer with byte-identical
  mode-3 finalization.
- Main operator pages have no preview collisions. Keyboard overlay pages retain
  their expected editor-layer intersections.

## USB installation evidence

- A new 4 MB pre-update backup was read and verified against the device-side MD5
  before writing. SHA-256:
  `adece431c077f213f9040b42d0696edd78390e4a2e2bba1e58e182ca04dab204`.
- The application write was followed by application, first-64-KiB and complete
  data-region digest checks. The updater reported `verified_held_in_rom`.
- The TJC screen acknowledged all 1,753,064 bytes, booted the new project and
  emitted two V4 heartbeats. The bridge then returned the ESP32 to ROM.
- A bounded paired boot reported `3.6.0-rc4`, `screen_ready=true`, healthy
  storage/journal, three preserved programs, and pump settings A=10 s/B=10 s.
- With the home input active, automatic preparation had reached dual drainage at
  8.9 seconds. This confirms the removed startup delay. Motor/pump power remained
  isolated, and the controller was returned to ROM after the observation.

## Release artifacts

- ESP32 application `washer-3.6.0-rc4.bin`: 1,117,952 bytes,
  SHA-256 `1771a1d92e0bc420746b83d9bc0c918058d96c231ef14f06ebe6df69cea577c5`.
- Screen `washer-native-v4.tft`: 1,753,064 bytes,
  SHA-256 `c5deeed6b1c13267c1ecaf991cc5427d0a01c73858562c6de99537c5837199b9`.
- Source `washer-native-v4.HMI`: 8,208,455 bytes,
  SHA-256 `695bac1230d7619e257aa7046f8236960921edadca44333a48b989cc4423effe`.

These checks do not constitute physical commissioning. RC4 was installed as a
paired controller/screen update with motor and pump power isolated. Its next
powered boot will promptly start automatic homing and the 20-second dual-drain
preparation sequence.
