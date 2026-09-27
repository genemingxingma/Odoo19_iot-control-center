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
constexpr uint8_t Font = 1;

// Keep execution states separate from cosmetic HMI page numbers.
enum ControllerPage : uint8_t {
    Overview = 0, Review = 1, Settings = 2, SdConfirm = 3, Loading = 4,
    Programs = 5, Wifi = 6, LegacyKeyboard = 7, LoadingReference = 8,
    StartupStatus = 9, PumpTimes = 10, Maintenance = 11
};

enum NativePage : uint8_t {
    BootPage = 0, HomePage = 1, SettingsPage = 2, ProgramsPage = 3,
    StartupPage = 4, ReadyPage = 5, RunningPage = 6, LoadingPage = 7,
    WifiPage = 8, PumpPage = 9, MaintenancePage = 10, FaultPage = 11,
    FinishedPage = 12, SdConfirmPage = 13
};

struct View {
    String state, program, step, cycle, temperature, remaining, notice, detail, networkStatus, deviceId;
    bool startup = false, running = false, waiting = false, ready = false, door = false, openRotor = false;
    bool loadingReady = false, moving = false, canCalibrate = false;
    uint8_t slot = instrument::BalancedLoading::Unknown, targetSlot = 0;
    unsigned progress = 0, loadingDegrees = 0;
    String programChoice, wifiSsid, wifiPassword;
    uint8_t programCount = 0, selectedProgram = 0;
    bool unsaved = false, fault = false, completed = false;
    uint16_t pumpA = 0, pumpB = 0;
};

class Display {
    String pending;
    String scene[24];
    unsigned sceneCount = 0, sceneCursor = 0;
    size_t sent = 0;
    uint8_t renderedNativePage = 255;
    uint32_t presentedAt = 0;
    bool presenting = false;

    static String safe(String value) {
        value.replace("\\", "/");
        value.replace("\"", "'");
        value.replace("\r\n", "\n");
        value.replace("\r", "\n");
        value.replace("\n", "\\r");
        return value;
    }
    void command(const String& value) {
        bool changed = renderedNativePage == 255 || sceneCursor >= sceneCount ||
                       sceneCursor >= 24 || scene[sceneCursor] != value;
        if (sceneCursor < 24) scene[sceneCursor] = value;
        ++sceneCursor;
        if (changed) {
            pending += value;
            pending += "\xff\xff\xff";
        }
    }
    void text(const char* object, const String& value) {
        command(String(object) + ".txt=\"" + safe(value) + "\"");
    }
    void color(const char* object, uint16_t background, uint16_t foreground) {
        command(String(object) + ".bco=" + String(background));
        command(String(object) + ".pco=" + String(foreground));
    }
    uint8_t nativePage(const View& view) const {
        if (view.fault) return FaultPage;
        if (view.startup) return StartupPage;
        if (view.waiting) return LoadingPage;
        if (view.running) return RunningPage;
        if (view.completed && page == Overview) return FinishedPage;
        switch (page) {
            case Review: return ReadyPage;
            case Settings: return SettingsPage;
            case SdConfirm: return SdConfirmPage;
            case Loading: case LoadingReference: return LoadingPage;
            case Programs: return ProgramsPage;
            case Wifi: case LegacyKeyboard: return WifiPage;
            case PumpTimes: return PumpPage;
            case Maintenance: return MaintenancePage;
            default: return HomePage;
        }
    }
    void finishFrame() {
        for (unsigned i = sceneCursor; i < sceneCount && i < 24; ++i) scene[i] = "";
        sceneCount = sceneCursor;
        if (!busy()) presenting = false;
    }

public:
    bool dirty = true;
    uint8_t page = Overview;

    Display() { pending.reserve(2048); }
    bool busy() const { return sent < pending.length(); }
    bool acceptsAction(uint32_t now) const {
        return renderedNativePage != 255 && !presenting && !dirty &&
               instrument::elapsed(now, presentedAt) >= 150u;
    }
    void invalidate() {
        renderedNativePage = 255;
        sceneCount = 0;
        dirty = true;
    }
    void render(const View& view) {
        if (busy()) return;
        const uint8_t wanted = nativePage(view);
        const bool pageChanged = wanted != renderedNativePage;
        if (pageChanged) {
            renderedNativePage = wanted;
            sceneCount = 0;
            presenting = true;
        }
        pending = "";
        sent = 0;
        sceneCursor = 0;
        if (pageChanged) {
            pending += "page page" + String(wanted);
            pending += "\xff\xff\xff";
        }

        switch (wanted) {
            case HomePage:
                text("t1", view.program);
                text("t2", view.notice.length() ? view.notice : "Choose a program, then review before starting.");
                break;
            case SettingsPage:
                text("t1", view.deviceId);
                text("t2", view.detail + "\n" + view.networkStatus + "\n" +
                     (view.notice.length() ? view.notice : "Wi-Fi and fill times are stored on this washer."));
                break;
            case ProgramsPage:
                text("t1", view.programCount ? view.programChoice : "No programs available");
                text("t2", view.programCount ? "Program " + String(view.selectedProgram + 1) +
                     " of " + String(view.programCount) + "\nUse Previous and Next, then select this program."
                     : "Connect to IoT Center to synchronize programs.");
                color("b1", view.programCount ? Blue : Muted, White);
                break;
            case StartupPage:
                text("t1", view.step);
                text("t2", view.notice + (view.remaining.length() ? "\n" + view.remaining : ""));
                break;
            case ReadyPage:
                text("t1", view.program);
                text("t2", view.notice.length() ? view.notice : view.step);
                color("b0", view.ready ? Blue : Muted, White);
                break;
            case RunningPage:
                text("t1", view.program);
                text("t2", view.step + (view.cycle.length() ? "\n" + view.cycle : "") +
                     (view.remaining.length() ? "\n" + view.remaining : "") +
                     (view.temperature.length() ? "\nTemperature " + view.temperature : ""));
                break;
            case LoadingPage: {
                String position = view.slot == instrument::BalancedLoading::Unknown ? "Position not aligned" :
                    "Current slot " + String(view.slot + 1) + " | Next " + String(view.targetSlot + 1) +
                    " (" + String(view.loadingDegrees) + " deg)";
                text("t1", view.step);
                text("t2", position + "\n" + view.notice);
                text("b0", view.moving ? "Moving..." : !view.loadingReady ?
                     (view.canCalibrate ? "Set Slot 1" : "Calibration Required") :
                     view.slot == instrument::BalancedLoading::Unknown ? "Align Start" : "Next Position");
                color("b0", view.moving || (!view.loadingReady && !view.canCalibrate) ? Muted : Blue, White);
                break;
            }
            case WifiPage:
                text("t1", view.wifiSsid);
                text("t2", view.wifiPassword);
                text("b2", view.detail);
                break;
            case PumpPage:
                text("t1", "Buffer A\n" + String(view.pumpA) + " s");
                text("t2", "Buffer B\n" + String(view.pumpB) + " s");
                text("b2", view.notice.length() ? view.notice :
                     "Tap left for A, right for B. Stored locally for offline use.");
                break;
            case MaintenancePage:
                text("t1", view.state);
                text("t2", view.notice.length() ? view.notice : "Service actions never start a wash program.");
                break;
            case FaultPage:
                text("t1", "Instrument stopped");
                text("t2", view.notice);
                break;
            case FinishedPage:
                text("t1", view.program);
                text("t2", "Program finished. Confirm the rotor is stationary.");
                break;
            case SdConfirmPage:
                text("t1", "Install the washer update from the SD card?");
                text("t2", "Keep power on. Outputs remain off during validation.");
                break;
            default: break;
        }
        dirty = false;
        finishFrame();
    }
    void tick(HardwareSerial& serial, uint32_t now) {
        if (!busy()) return;
        size_t count = min(static_cast<size_t>(serial.availableForWrite()),
                           min(size_t(128), pending.length() - sent));
        if (count) sent += serial.write(reinterpret_cast<const uint8_t*>(pending.c_str() + sent), count);
        if (!busy() && presenting) {
            presenting = false;
            presentedAt = now;
        }
    }
    // Native controls emit explicit line commands. Coordinate packets from a
    // legacy screen are ignored and can never invoke a machine action.
    int touch(uint8_t, uint32_t) { return -1; }
    bool receivingTouch() const { return false; }
};
}
