#pragma once
#include <Arduino.h>
#include "control.hpp"
#include "washer_setup.hpp"

namespace tjc {
constexpr uint16_t rgb565(unsigned r, unsigned g, unsigned b) {
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}
constexpr uint16_t Background = rgb565(243, 248, 255), Header = rgb565(15, 67, 122),
    Ink = rgb565(35, 69, 104), Muted = rgb565(81, 107, 133), Blue = rgb565(20, 104, 192),
    Button = rgb565(216, 233, 250), Disabled = rgb565(225, 234, 243), White = 65535,
    Red = rgb565(192, 40, 64);
constexpr uint8_t Font = 1;  // Verdana Bold 24 px, ASCII-only screen resource.
struct View {
    String state, program, step, temperature, remaining, notice, detail;
    bool running = false, waiting = false, ready = false, door = false, openRotor = false;
    bool loadingReady = false, moving = false;
    uint8_t slot = instrument::BalancedLoading::Unknown, targetSlot = 0;
    unsigned progress = 0, loadingDegrees = 0;
    String programs[3], wifiSsid, wifiMasked, wifiEntry;
    uint8_t programCount = 0, selectedProgram = 0, keyboard = 0;
    unsigned libraryPage = 0, libraryPages = 1;
    bool passwordField = false;
};
class Display {
    String pending;
    size_t sent = 0;
    uint8_t packet[9] = {}, length = 0;
    uint32_t receivedAt = 0, pressedAt = 0;
    int pressed = -1;
    bool loadingMoveEnabled = false, loadingContinueEnabled = false;
    uint8_t loadingSlot = instrument::BalancedLoading::Unknown;
    uint8_t renderedPage = 255;
    uint32_t presentedAt = 0;
    bool presenting = false;
public:
    bool dirty = true;
    uint8_t page = 0;
    // 5=program library, 6=Wi-Fi, 7=keyboard, 9=initialize confirmation.
    Display() { pending.reserve(4608); }
    bool busy() const { return sent < pending.length(); }
    bool acceptsAction(uint32_t now) const {
        return page == renderedPage && !presenting && !dirty && instrument::elapsed(now, presentedAt) >= (page >= 5 ? 120u : 750u);
    }
    void command(const String& value) { pending += value; pending += "\xff\xff\xff"; }
    void text(int x, int y, int w, int h, const String& value, uint16_t color = Ink, uint16_t bg = Background, int align = 0) {
        String safe = value; safe.replace("\"", "'"); safe.replace("\\", "/"); safe.replace("\n", " "); safe.replace("\r", " ");
        command("xstr " + String(x)+","+String(y)+","+String(w)+","+String(h)+","+String(Font)+","+String(color)+","+String(bg)+","+String(align)+",1,1,\""+safe+"\"");
    }
    void fill(int x, int y, int w, int h, uint16_t color) {
        command("fill "+String(x)+","+String(y)+","+String(w)+","+String(h)+","+String(color));
    }
    void render(const View& v) {
        if (busy()) return;
        if (renderedPage != page) { pressed = -1; dirty = true; }
        if (page == 4) {
            bool moveEnabled = v.loadingReady && !v.moving;
            bool continueEnabled = v.ready && !v.moving;
            if (moveEnabled != loadingMoveEnabled || continueEnabled != loadingContinueEnabled || loadingSlot != v.slot) {
                pressed = -1; dirty = true;
            }
            loadingMoveEnabled = moveEnabled; loadingContinueEnabled = continueEnabled; loadingSlot = v.slot;
        }
        bool redraw = renderedPage != page || dirty;
        // Invalidate any touch-down whenever content is redrawn. This prevents
        // a release from an old program card confirming newly synced content.
        if (redraw) { pressed = -1; presenting = true; renderedPage = page; }
        pending = ""; sent = 0;
        if (dirty) { command("cls "+String(Background)); dirty = false; }
        if (page >= 5) {
            fill(0, 0, 800, 62, Header);
            fill(0, 62, 800, 4, Blue);
            text(24, 10, 752, 42, page == 5 ? "PROGRAMS" : page == 6 ? "WI-FI / 2.4 GHz" : page == 7 ? (v.passwordField ? "ENTER WI-FI PASSWORD" : "ENTER NETWORK NAME") : "INITIALIZE INSTRUMENT", White, Header);
            if (page == 5) {
                text(24, 76, 752, 32, "Select a program.", Muted);
                for (unsigned i = 0; i < 3; ++i) text(24, 122+i*76, 752, 64,
                    i < v.programCount ? v.programs[i] : (i == 0 ? "No programs. Connect to IoT Center to sync." : ""), i < v.programCount && i == v.selectedProgram ? White : Ink, i < v.programCount && i == v.selectedProgram ? Blue : Button);
                text(24, 354, 360, 32, "< PREVIOUS", Muted);
                text(400, 354, 376, 32, "NEXT >  "+String(v.libraryPage+1)+" / "+String(v.libraryPages), Muted);
            } else if (page == 6) {
                text(24, 78, 752, 32, v.detail, Muted);
                text(24, 126, 752, 60, "Network: " + v.wifiSsid, Ink, White);
                text(24, 198, 752, 60, "Password: " + v.wifiMasked, Ink, White);
                text(24, 270, 752, 32, "Tap a field to edit. Empty password = open network.", Muted);
                text(24, 314, 752, 68, v.notice, Ink);
            } else if (page == 7) {
                text(24, 76, 752, 64, v.wifiEntry, Ink, White);
                if (redraw) {
                    const char* keys = instrument::WifiDraft::keys(v.keyboard);
                    for (unsigned i = 0; i < 40; ++i) {
                        char key[] = {keys[i], 0};
                        String label = keys[i] == '"' ? "DQ" : keys[i] == '\\' ? "BSL" : key;
                        text(24+(i%10)*75, 150+(i/10)*50, 69, 44, label, Ink, Button, 1);
                    }
                    const char* labels[] = {"DELETE", "aA", "SYMBOLS", "SPACE"};
                    for (unsigned i = 0; i < 4; ++i) text(24+i*188, 354, 180, 36, labels[i], Ink, Button, 1);
                }
            } else {
                text(24, 124, 752, 96, "Home the rotor, then run BOTH drain pumps for 20 seconds.");
                text(24, 240, 752, 96, "Keep hands clear. Check drain tubing. STOP cancels initialization.", Red);
            }
            text(24,400,242,58,page==5?"USE PROGRAM":page==6?"SAVE / CONNECT":page==7?"DONE":"CONFIRM",White,Blue,1);
            text(280,400,242,58,"BACK",Ink,Button,1);
            text(536,400,240,58,"STOP",White,Red,1);
            return;
        }
        fill(0, 0, 800, 62, Header);
        fill(0, 62, 800, 4, Blue);
        text(24, 10, 472, 42, "iMYTEST / ARRAY WASHER", White, Header);
        fill(512, 10, 264, 42, Blue);
        text(524, 10, 240, 42, v.state, White, Blue, 2);
        text(24, 78, 748, 32, page == 0 ? "RUN OVERVIEW" : page == 1 ? "REVIEW BEFORE START" : page == 2 ? "DEVICE CARE" : page == 4 ? "PAUSED / LOAD SLIDES" : "CONFIRM SD UPDATE", Muted);
        if (page == 4) {
            text(24, 116, 752, 32, "Load opposite slots in pairs. Pumps remain OFF.", Muted);
            for (unsigned i = 0; i < 6; ++i) {
                uint8_t slot = instrument::BalancedLoading::Order[i];
                bool current = !v.moving && slot == v.slot, target = v.moving && slot == v.targetSlot;
                // Each column is an opposite pair; these are indicators, not buttons.
                text(24 + (i / 2) * 256, 160 + (i % 2) * 72, 240, 56,
                     String(i + 1) + ". SLOT " + String(slot + 1), current || target ? White : Ink,
                     current ? Blue : target ? Muted : Button, 1);
            }
            text(24, 304, 752, 76, v.notice, v.loadingReady ? Ink : Red);
        } else if (page <= 1) {
            fill(16, 116, 768, 146, White);
            text(24, 124, 748, 36, v.program, Ink, White);
            text(24, 174, 450, 36, v.step, Ink, White);
            text(514, 174, 250, 36, v.remaining, Ink, White, 2);
            text(24, 222, 450, 36, "Buffer: " + v.temperature, Ink, White);
            fill(24, 278, 752, 10, Header); fill(24, 278, v.progress * 752 / 100, 10, Blue);
            text(24, 308, 752, 38, page == 1 ? "Check program and liquid. Keep hands clear; confirm start." : v.notice, v.ready ? Ink : Red);
            if (page == 0) text(24, 354, 752, 32, "DEVICE CARE / WI-FI", Muted);
        } else {
            text(24, 124, 748, 44, page == 3 ? "Install the update from the SD card?" : "Settings and maintenance");
            text(24, 214, 748, 68, page == 3 ? "Keep power on. All outputs remain off during update." : v.detail);
            text(24, 308, 748, 68, page == 3 ? "" : "Reset clears the fault. It does not restart the run.");
            if (page == 2) {
                text(24, 174, 360, 38, "WI-FI SETTINGS", Ink, Button, 1);
                text(400, 174, 376, 38, "INITIALIZE", Ink, Button, 1);
                text(24, 272, 360, 32, "BACK TO OVERVIEW", Muted);
            }
        }
        text(24, 400, 242, 58, page == 4 ? (v.moving ? "WAIT FOR STOP" : "CONTINUE") : page == 0 ? (v.waiting ? "CONTINUE" : v.running ? "RUNNING" : "REVIEW / START") : page == 1 ? "CONFIRM START" : page == 2 ? "RESET FAULT" : "INSTALL", White, v.moving && page == 4 ? Muted : Blue, 1);
        String loadingAction = v.moving ? "MOVING..." : !v.loadingReady ? "NOT CALIBRATED" :
            v.slot == instrument::BalancedLoading::Unknown ? "ALIGN START" : "NEXT +" + String(v.loadingDegrees);
        text(280, 400, 242, 58, page == 4 ? loadingAction : page == 0 ? "PROGRAMS" : page == 2 ? "SD UPDATE" : "BACK", Ink, page == 4 && !loadingMoveEnabled ? Disabled : Button, 1);
        text(536, 400, 240, 58, "STOP", White, Red, 1);
    }
    void tick(HardwareSerial& serial, uint32_t now) {
        if (!busy()) return;
        size_t count = min(static_cast<size_t>(serial.availableForWrite()), min(size_t(128), pending.length()-sent));
        if (count) sent += serial.write(reinterpret_cast<const uint8_t*>(pending.c_str()+sent), count);
        if (!busy() && presenting) { presenting = false; presentedAt = now; }
    }
    int touch(uint8_t value, uint32_t now) {
        if (length && instrument::elapsed(now, receivedAt) > 100) { length = 0; pressed = -1; }
        receivedAt = now;
        if (!length && value != 0x67) return -1;
        packet[length++] = value;
        if (length != sizeof(packet)) return -1;
        length = 0;
        if (packet[6] != 255 || packet[7] != 255 || packet[8] != 255) { pressed = -1; return -1; }
        unsigned x = packet[1]*256u+packet[2], y = packet[3]*256u+packet[4];
        int button = y >= 400 && y < 458 ? (x >= 24 && x < 266 ? 0 : x >= 280 && x < 522 ? 1 : x >= 536 && x < 776 ? 2 : -1) : -1;
        if (x >= 24 && x < 776) {
            if (page == 0 && y >= 354 && y < 386) button = 3;
            if (page == 2 && y >= 174 && y < 212) button = x < 384 ? 3 : x >= 400 ? 4 : -1;
            if (page == 2 && x < 384 && y >= 272 && y < 304) button = 5;
            if (page == 5) {
                for (unsigned i=0; i<3; ++i) if (y >= 122+i*76 && y < 186+i*76) button = 10+i;
                if (y >= 354 && y < 386) button = x<384?3:x>=400?4:-1;
            }
            if (page == 6 && y >= 126 && y < 186) button = 3;
            if (page == 6 && y >= 198 && y < 258) button = 4;
            if (page == 7 && y >= 150 && y < 350 && (x-24)/75 < 10 && (x-24)%75 < 69 && (y-150)%50 < 44) button = 10+(y-150)/50*10+(x-24)/75;
            if (page == 7 && y >= 354 && y < 390 && (x-24)%188 < 180) button = 50+(x-24)/188;
        }
        if (page == 4 && ((button == 1 && !loadingMoveEnabled) || (button == 0 && !loadingContinueEnabled))) button = -1;
        if (packet[5] == 1 && page == 4 && button != 2 && !acceptsAction(now)) {
            pressed = -1; return -1;
        }
        if (packet[5] == 1) { pressed = button; pressedAt = now; return button == 2 ? 2 : -1; }
        int result = packet[5] == 0 && button == pressed && instrument::elapsed(now, pressedAt) < 5000 ? button : -1;
        pressed = -1;
        return result == 2 ? -1 : result;
    }
    bool receivingTouch() const { return length != 0; }
};
}
