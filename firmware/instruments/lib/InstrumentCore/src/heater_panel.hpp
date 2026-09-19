#pragma once
#include <cstdint>

namespace instrument {
enum class HeaterPage { Live, Identity, Target };
enum class HeaterAction { None, Enable, Stop, Acknowledge };
class HeaterPanel {
    uint8_t raw = 0, stable = 0;
    uint32_t changed = 0, heatPressed = 0, pageAt = 0;
    bool initialized = false, ready = false, heatBlocked = false, handled = false;
public:
    HeaterPage page = HeaterPage::Live;
    void inhibitHeatUntilRelease() { heatBlocked = true; handled = true; }
    HeaterAction poll(uint32_t now, uint8_t down, bool enabled, bool fault) {
        down &= 7;
        if (!initialized) { raw = down; changed = now; initialized = true; }
        if (page != HeaterPage::Live && uint32_t(now - pageAt) >= 10000) page = HeaterPage::Live;
        if (down != raw) { raw = down; changed = now; }
        if (uint32_t(now - changed) < 40) return HeaterAction::None;
        uint8_t pressed = raw & ~stable;
        stable = raw;
        if (!stable) { ready = true; heatBlocked = handled = false; }
        if (!ready) return HeaterAction::None;
        if ((stable & 2) && enabled) { heatBlocked = handled = true; page = HeaterPage::Live; return HeaterAction::Stop; }
        // Chords cannot authorize heat, even after one key has been released.
        if (stable & (stable - 1)) { heatBlocked = true; return HeaterAction::None; }
        if (pressed & 1) { page = HeaterPage::Identity; pageAt = now; }
        if (pressed & 4) { page = HeaterPage::Target; pageAt = now; }
        if (pressed & 2) {
            heatPressed = now; page = HeaterPage::Live;
            if (!fault && !heatBlocked) { handled = true; return HeaterAction::Enable; }
        }
        if (stable == 2 && fault && !heatBlocked && !handled && uint32_t(now - heatPressed) >= 1500) {
            handled = heatBlocked = true;
            return HeaterAction::Acknowledge;
        }
        return HeaterAction::None;
    }
};

struct HeaterView {
    const char* state = "SETUP";
    const char* temperature = "--.-";
    const char* target = "NOT SET";
    const char* chip = "------";
    const char* ip = "NOT CONNECTED";
    const char* version = "";
    const char* alarm = "";
    bool online = false, output = false;
    HeaterPage page = HeaterPage::Live;
};

// Uses common Adafruit GFX primitives; exercised with a host display double.
template<class Display> void drawHeater(Display& d, const HeaterView& v) {
    d.clearDisplay(); d.setTextColor(1); d.setTextWrap(false); d.setTextSize(1);
    d.setCursor(0, 0); d.print(v.state);
    d.setCursor(80, 0); d.print(v.online ? "ONLINE" : "OFFLINE");
    d.drawLine(0, 9, 127, 9, 1);
    if (v.page == HeaterPage::Identity) {
        d.setCursor(0, 14); d.print("ID "); d.print(v.chip);
        d.setCursor(0, 26); d.print(v.ip);
        d.setCursor(0, 38); d.print("FW "); d.print(v.version);
    } else if (v.page == HeaterPage::Target) {
        d.setCursor(0, 14); d.print("STORED SETPOINT");
        d.setTextSize(2); d.setCursor(0, 27); d.print(v.target);
    } else {
        d.setTextSize(3); d.setCursor(0, 13); d.print(v.temperature);
        d.setTextSize(1); d.setCursor(113, 26); d.print("C");
        d.setCursor(0, 39); d.print("SET "); d.print(v.target);
        d.setCursor(86, 39); d.print(v.output ? "OUT ON" : "OUT OFF");
    }
    d.setTextSize(1); d.drawLine(0, 48, 127, 48, 1); d.setCursor(0, 54);
    d.print(v.alarm[0] ? v.alarm : "1:ID  2:HEAT  3:SET");
    d.display();
}
}
