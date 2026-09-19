# TJC8048X550_011C interface

Target confirmed by the user and the original project in USART HMI 1.68.1:
800 x 480 landscape, GB2312. The original project compiles with zero errors and
zero warnings. It is preserved in the imported source archive.

The redesigned project is separate. Do not install it with the legacy washer
firmware: the controller and screen use a new, versioned interface.

`washer-v3.HMI` was created and compiled by the official editor with zero errors
and zero warnings. Font 0 retains the supplied songti_24 GB2312 font as a
rollback resource. Font 1 is the generated `washer_sans_24_bold` resource:
24-pixel antialiased Verdana Bold with an ASCII-only character set. The washer
interface is English-only and the ESP32 renderer intentionally uses font 1.
`page-init.txt` is the page post-initialization event. Timer tm1 sends
`heartbeat.txt` every 400 ms; tm0 is unused. Touch coordinates use the
documented 0x67 frame.

The ESP32 draws the 800x480 interface with bounded, nonblocking serial writes.
`include/tjc_ui.hpp` owns layout and touch hitboxes. The host test emits the
same drawing commands for the official simulator, not an HTML approximation.
The screen waits for its controller rather than displaying invented live data.
The simulator fixture contains synthetic values only.

Status: compiler and representative simulator checks passed; no real hardware
has been flashed or commissioned. The TFT is a test artifact, not a production
release. Never use the legacy screen with V3 controller firmware.
