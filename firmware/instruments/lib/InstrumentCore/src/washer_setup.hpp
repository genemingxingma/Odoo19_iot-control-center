#pragma once
#include "control.hpp"
#include <vector>

namespace instrument {
class ProgramLibrary {
public:
    static constexpr size_t MaximumPrograms = 64;
    // Bound RAM consumption on the 4MB/no-PSRAM controller and keep the wire
    // contract identical to the platform even when more RAM is available.
    static constexpr size_t MemoryBudget = 48 * 1024;
    static constexpr size_t MemoryCapacity = MemoryBudget / sizeof(Recipe);
    static constexpr size_t Capacity = MemoryCapacity < MaximumPrograms ? MemoryCapacity : MaximumPrograms;
    std::vector<Recipe> items;
    uint8_t count = 0, selected = 0;
    int find(const char* id) const {
        for (uint8_t i = 0; i < count; ++i) if (!strcmp(items[i].id, id)) return i;
        return -1;
    }
    bool put(const Recipe& p) {
        if (!validRecipe(p)) return false;
        int index = find(p.id);
        if (index >= 0 && p.revision < items[index].revision) return false;
        if (index >= 0 && p.revision == items[index].revision) {
            const Recipe& old = items[index];
            if (strcmp(old.label, p.label) || old.count != p.count) return false;
            for (uint8_t i=0; i<p.count; ++i) {
                const Step& a=old.steps[i]; const Step& b=p.steps[i];
                if (a.kind!=b.kind || a.duration!=b.duration || a.rps!=b.rps || a.reverseSeconds!=b.reverseSeconds || a.cycles!=b.cycles) return false;
            }
            return true;
        }
        if (index < 0) { if (count == Capacity) return false; index = count++; items.emplace_back(); }
        items[index] = p;
        return true;
    }
    bool select(uint8_t index) { if (index >= count) return false; selected = index; return true; }
    bool remove(uint8_t index) {
        if (index >= count) return false;
        for (uint8_t i = index; i + 1 < count; ++i) items[i] = items[i + 1];
        --count; items.pop_back();
        if (selected > index) --selected;
        if (selected >= count) selected = count ? count - 1 : 0;
        return true;
    }
};

class Startup {
public:
    enum Phase { Pending, Homing, Draining, Ready, Stopped };
    Phase phase = Pending;
    uint32_t entered = 0;
    bool active() const { return phase == Homing || phase == Draining; }
    bool start(uint32_t now, bool permitted) {
        if (!permitted || active() || phase == Ready) return false;
        phase = Homing; entered = now; return true;
    }
    // STOP always invalidates the ready state. A fresh home-and-drain cycle is
    // required before another run can start after any interruption.
    void stop() { phase = Stopped; }
    Fault tick(uint32_t now, bool safe, bool homed, bool stationary) {
        if (!active()) return None;
        if (!safe) { phase = Stopped; return DoorOpen; }
        if (phase == Homing) {
            if (elapsed(now, entered) >= 10000) { phase = Stopped; return HomeTimeout; }
            if (homed && stationary) { phase = Draining; entered = now; }
        } else if (elapsed(now, entered) >= 20000) phase = Ready;
        return None;
    }
    uint8_t drain() const { return phase == Draining ? WasherMotorProfile::DrainPwm : 0; }
};

struct WifiDraft {
    char ssid[33] = {}, password[65] = {};
    bool passwordField = false;
    uint8_t keyboard = 0;
    static const char* keys(uint8_t mode) {
        if (mode == 1) return "1234567890QWERTYUIOPASDFGHJKL-ZXCVBNM_./";
        if (mode == 2) return "!@#$%^&*()[]{}<>?=+|\"'\\:;,`~_-0123456789";
        return "1234567890qwertyuiopasdfghjkl-zxcvbnm_./";
    }
    bool append(char c) {
        char* target = passwordField ? password : ssid;
        size_t size = strlen(target), limit = passwordField ? 64 : 32;
        if (c < 32 || c > 126 || size >= limit) return false;
        target[size] = c; target[size + 1] = 0; return true;
    }
    void backspace() {
        char* target = passwordField ? password : ssid;
        size_t size = strlen(target); if (size) target[size - 1] = 0;
    }
    bool valid() const {
        size_t length = strlen(password);
        if (!ssid[0] || (length && length < 8)) return false;
        if (length == 64) for (char c : password) {
            if (c && !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) return false;
        }
        return true;
    }
    void clear() { memset(ssid, 0, sizeof(ssid)); memset(password, 0, sizeof(password)); passwordField = false; keyboard = 0; }
};
}
