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
    const char* deviceId = "HTR------------";
    const char* ip = "NOT CONNECTED";
    const char* version = "";
    const char* alarm = "";
    bool online = false, output = false, fault = false;
    bool targetSaved = true;
    HeaterPage page = HeaterPage::Live;
};

// Uses common Adafruit GFX primitives; exercised with a host display double.
template<class Display> void drawHeater(Display& d, const HeaterView& v) {
    d.clearDisplay(); d.setTextColor(1); d.setTextWrap(false); d.setTextSize(1);
    if (v.fault) {
        d.setTextSize(2); d.setCursor(0, 3); d.print("ALARM");
        d.drawLine(0, 22, 127, 22, 1);
        d.setTextSize(1); d.setCursor(0, 30); d.print(v.alarm);
        d.setCursor(0, 48); d.print("HEAT OFF");
    } else if (v.page == HeaterPage::Identity) {
        d.setCursor(0, 0); d.print("DEVICE ID");
        char first[9] = {};
        for (uint8_t i = 0; i < 8 && v.deviceId[i]; ++i) first[i] = v.deviceId[i];
        d.setTextSize(2); d.setCursor(0, 13); d.print(first);
        d.setCursor(0, 32); d.print(v.deviceId + 8);
        d.setTextSize(1); d.setCursor(0, 54); d.print(v.ip);
    } else if (v.page == HeaterPage::Target) {
        d.setCursor(0, 0); d.print("TARGET");
        d.setTextSize(3); d.setCursor(0, 19); d.print(v.target);
        d.setTextSize(1); d.setCursor(0, 54); d.print(v.targetSaved ? "SAVED ON DEVICE" : "DEFAULT SETPOINT");
    } else {
        d.setCursor(0, 0); d.print(v.output ? "HEATING" : v.state);
        d.setCursor(120, 0); d.print("C");
        d.setTextSize(4); d.setCursor(0, 13); d.print(v.temperature);
        d.setTextSize(1); d.setCursor(0, 54); d.print("TARGET "); d.print(v.target);
    }
    d.display();
}
}
