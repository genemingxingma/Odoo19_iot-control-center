#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
#include "motor_profile.hpp"

namespace instrument {
inline uint32_t elapsed(uint32_t now, uint32_t then) { return now - then; }
constexpr uint8_t pwmPercent(uint8_t percent) {
    return static_cast<uint8_t>(((percent > 100 ? 100u : percent) * 255u + 50u) / 100u);
}
class ExchangeSchedule {
    bool liveNext = true;
public:
    bool useBacklog(bool available) {
        if (!available) { liveNext = true; return false; }
        bool backlog = !liveNext;
        liveNext = !liveNext;
        return backlog;
    }
};
enum Fault : uint8_t { None, NotCommissioned, Sensor, NoTemperatureRise, OverTemperature, HomeTimeout, DoorOpen, RunTimeout, Storage };
struct Probe {
    float value = 0;
    uint32_t sampled = 0;
    bool valid = false;
};
struct HeaterChannel {
private:
    static constexpr float Kp = 20.0f, Ki = Kp / 600.0f;
    static constexpr uint32_t ControlMs = 1000, WindowMs = 2000, MinPulseMs = 20;
    float integral = 0, power = 0;
    uint32_t lastControl = 0, windowStarted = 0;
    bool controlReady = false;
    static float clampPower(float value) { return value < 0 ? 0 : value > 100 ? 100 : value; }
    void resetControl() { integral = power = 0; controlReady = output = demand = false; }
public:
    float target = 42;
    bool enabled = false, output = false, demand = false;
    Fault fault = None;
    uint32_t riseWindowMs = 0, poweredMs = 0, lastTick = 0;
    float minimumRise = 0, reference = 0;
    bool tracking = false, clockReady = false;
    bool configureProtection(uint32_t seconds, float rise) {
        if (seconds < 30 || seconds > 3600 || !std::isfinite(rise) || rise < 0.125f || rise > 5) return false;
        if (enabled && (riseWindowMs != seconds * 1000u || minimumRise != rise)) return false;
        riseWindowMs = seconds * 1000u; minimumRise = rise; return true;
    }
    bool setTarget(float value) {
        if (!std::isfinite(value) || value < 10 || value > 50 || std::round(value * 4) != value * 4) return false;
        if (target != value) { resetControl(); tracking = false; poweredMs = 0; }
        target = value;
        return true;
    }
    float powerPercent() const { return power; }
    void stop() { resetControl(); enabled = tracking = clockReady = false; poweredMs = 0; }
    void account(uint32_t now) {
        if (clockReady && output && tracking) {
            uint32_t delta = elapsed(now, lastTick);
            poweredMs = delta >= riseWindowMs - poweredMs ? riseWindowMs : poweredMs + delta;
        }
        lastTick = now; clockReady = true;
    }
    void pause(uint32_t now) { account(now); output = false; controlReady = false; }
    Fault condition(const Probe& p, uint32_t now) const {
        if (!p.valid || !std::isfinite(p.value) || p.value < -20 || p.value >= 85 || elapsed(now, p.sampled) > 3000) return Sensor;
        if (p.value >= 55) return OverTemperature;
        return None;
    }
    bool arm(const Probe& p, uint32_t now) {
        Fault current = condition(p, now);
        if (!riseWindowMs) { fault = NotCommissioned; stop(); return false; }
        if (current != None) { fault = current; stop(); return false; }
        resetControl(); windowStarted = now;
        fault = None; enabled = true;
        poweredMs = 0; tracking = false; clockReady = true; lastTick = now; return true;
    }
    void tick(const Probe& p, uint32_t now) {
        account(now);
        Fault current = condition(p, now);
        if (enabled && current != None) { fault = current; stop(); }
        if (!enabled || fault != None) { resetControl(); return; }
        if (p.value >= target + 1.0f) {
            resetControl(); tracking = false; poweredMs = 0; return;
        }
        const float error = target - p.value;
        if (!controlReady || elapsed(now, lastControl) >= ControlMs) {
            // Never integrate a blocking maintenance interval or build up a
            // hidden full-power demand while the PI output is saturated.
            if (controlReady) {
                float seconds = (elapsed(now, lastControl) > ControlMs ? ControlMs : elapsed(now, lastControl)) / 1000.0f;
                float candidate = clampPower(integral + Ki * error * seconds);
                if (Kp * error + candidate <= 100 || error < 0) integral = candidate;
            }
            power = clampPower(Kp * error + integral);
            lastControl = now; controlReady = true;
        }
        uint32_t phase = elapsed(now, windowStarted);
        if (phase >= WindowMs) { windowStarted += phase - phase % WindowMs; phase %= WindowMs; }
        uint32_t onMs = static_cast<uint32_t>(power * WindowMs / 100.0f);
        // Do not send sub-cycle pulses to an AC SSR (50/60 Hz).
        if (onMs < MinPulseMs) onMs = 0;
        else if (WindowMs - onMs < MinPulseMs) onMs = WindowMs;
        demand = onMs > 0;
        output = demand && phase < onMs;
        // A stable holding temperature is not a failed heating response.
        // Below the holding band, count actual SSR-on time, not wall time.
        if (error <= 1.0f) { tracking = false; poweredMs = 0; }
        else if (demand && !tracking) { tracking = true; reference = p.value; poweredMs = 0; }
        if (tracking && poweredMs >= riseWindowMs) {
            if (p.value - reference < minimumRise) { fault = NoTemperatureRise; stop(); return; }
            reference = p.value; poweredMs = 0;
        }
    }
};

enum class StepKind : uint8_t { Home, FillA, FillB, Wash, Drain, Dry, Wait };
struct Step { StepKind kind = StepKind::Home; uint32_t duration = 10000; float rps = 0; uint16_t reverseSeconds = 5; uint16_t cycles = 0; };
struct Recipe {
    uint8_t schema = 1;
    char id[65] = "";
    char label[49] = "";
    uint32_t revision = 0;
    Step steps[32]; uint8_t count = 0;
};
inline bool validRecipe(const Recipe& p) {
    // Platform snapshots include the automatic pre-run home as step zero.
    if ((p.schema != 1 && p.schema != 2) || !p.id[0] || !p.revision || p.count < 2 || p.count > 32 || p.steps[0].kind != StepKind::Home) return false;
    // Logical recipe ordering only; no physical liquid-level sensor is present.
    bool liquid = false; uint32_t total = 0;
    for (uint8_t i = 0; i < p.count; ++i) {
        const Step& s = p.steps[i];
        bool localFill = p.schema == 2 && (s.kind == StepKind::FillA || s.kind == StepKind::FillB);
        if (static_cast<uint8_t>(s.kind) > 6 || (localFill ? s.duration != 0 : (s.duration < 1000 || s.duration > ((s.kind == StepKind::Wash || s.kind == StepKind::Wait) ? 3600000u : 300000u)))) return false;
        if (!std::isfinite(s.rps) || s.rps < 0 || s.rps > 10 || s.reverseSeconds < 1 || s.reverseSeconds > 60) return false;
        if (s.cycles && (s.kind != StepKind::Wash || s.cycles > 1800 || s.duration != uint32_t(s.cycles) * 2u * s.reverseSeconds * 1000u)) return false;
        bool motion = s.kind == StepKind::Wash || s.kind == StepKind::Dry;
        if ((motion && s.rps <= 0) || (!motion && s.rps != 0)) return false;
        if (s.kind == StepKind::FillA || s.kind == StepKind::FillB) { if (liquid) return false; liquid = true; }
        if (s.kind == StepKind::Wash && !liquid) return false;
        if (s.kind == StepKind::Drain) liquid = false;
        if (s.kind == StepKind::Dry && liquid) return false;
        if (s.kind != StepKind::Wait) total += localFill ? 300000u : s.duration;
    }
    return !liquid && total <= 14400000u;
}
struct Outputs {
    bool a = false, b = false;
    uint8_t drain = 0, overflow = 0;
    float rps = 0;
    void drainTogether(uint8_t duty) { drain = overflow = duty; }
};
// Absolute rounding avoids accumulating the fractional step in a 3200/6 pitch.
inline int32_t slotDelta(int32_t position, uint8_t slot, int32_t offset, int32_t revolution = WasherMotorProfile::StepsPerRevolution) {
    if (slot >= 6 || revolution < 6 || offset < 0 || offset >= revolution) return 0;
    int32_t current = position % revolution;
    if (current < 0) current += revolution;
    int32_t target = (offset + (int64_t(slot) * revolution + 3) / 6) % revolution;
    int32_t delta = target - current;
    if (delta > revolution / 2) delta -= revolution;
    if (delta < -revolution / 2) delta += revolution;
    return delta;
}
inline int32_t cyclicDelta(int32_t position, int32_t target, int32_t revolution = WasherMotorProfile::StepsPerRevolution) {
    if (revolution <= 0) return 0;
    position %= revolution; target %= revolution;
    if (position < 0) position += revolution;
    if (target < 0) target += revolution;
    int32_t delta = target - position;
    if (delta > revolution / 2) delta -= revolution;
    if (delta < -revolution / 2) delta += revolution;
    return delta;
}
class BalancedLoading {
public:
    static constexpr uint8_t Unknown = 255;
    inline static constexpr uint8_t Order[6] = {0, 3, 4, 1, 2, 5};
    static constexpr int32_t Revolution = WasherMotorProfile::StepsPerRevolution;
    uint8_t cursor = Unknown, pendingCursor = Unknown;
    bool active = false;
    int32_t distance = 0, target = 0;
    uint32_t began = 0, timeoutMs = 0;
    uint8_t currentSlot() const { return cursor == Unknown ? Unknown : Order[cursor]; }
    uint8_t nextCursor() const { return cursor == Unknown ? 0 : (cursor + 1) % 6; }
    uint8_t nextSlot() const { return Order[nextCursor()]; }
    unsigned nextDegrees() const { return cursor == Unknown ? 0 : cursor % 2 == 0 ? 180 : 60; }
    bool prime(int32_t position, int32_t offset, bool stopped, bool calibrated) {
        if (active || cursor != Unknown || !stopped || !calibrated || offset < 0 || offset >= Revolution) return false;
        if (slotDelta(position, 0, offset, Revolution) != 0) return false;
        cursor = 0; return true;
    }
    bool start(uint32_t now, int32_t position, int32_t offset, uint32_t hz, bool paused, bool stopped, bool calibrated) {
        if (active || !paused || !stopped || !calibrated || hz < WasherMotorProfile::LoadingMinHz || hz > WasherMotorProfile::LoadingMaxHz || offset < 0 || offset >= Revolution) return false;
        // The caller normalizes the stopped motor counter before issuing a move.
        if (position < 0 || position >= Revolution) return false;
        prime(position, offset, stopped, calibrated);
        if (cursor != Unknown && slotDelta(position, currentSlot(), offset, Revolution) != 0) return false;
        pendingCursor = nextCursor();
        distance = slotDelta(position, Order[pendingCursor], offset, Revolution);
        // After initial alignment, keep one direction: +180, +60, +180, +60...
        if (cursor != Unknown && distance < 0) distance += Revolution;
        if (!distance) return false;
        target = position + distance;
        uint32_t steps = static_cast<uint32_t>(distance < 0 ? -distance : distance);
        timeoutMs = (steps * 1000u + hz - 1) / hz + 2000u;
        active = true; began = now; return true;
    }
    bool expired(uint32_t now) const { return active && elapsed(now, began) >= timeoutMs; }
    bool complete(uint32_t now, bool stopped, int32_t position) {
        if (!active || !stopped || elapsed(now, began) < 25 || expired(now) || position != target) return false;
        cursor = pendingCursor; pendingCursor = Unknown; active = false; return true;
    }
    void reset() { cursor = pendingCursor = Unknown; active = false; distance = target = 0; began = timeoutMs = 0; }
};
class Washer {
public:
    Recipe program;
    Outputs outputs;
    Fault fault = None;
    bool running = false, waiting = false, finishing = false, finishingDrain = false, completed = false;
    uint8_t index = 0;
    uint32_t entered = 0, started = 0, lastTick = 0, activeMs = 0;
    bool load(const Recipe& value) {
        if (running || !validRecipe(value)) return false;
        program = value; completed = false; return true;
    }
    bool start(uint32_t now, bool commissioned, bool doorClosed) {
        if (running || !validRecipe(program) || !commissioned || !doorClosed || fault != None) return false;
        // Symbolic programs must be resolved against a device-local snapshot first.
        for (uint8_t i=0; i<program.count; ++i) if (!program.steps[i].duration) return false;
        running = true; completed = waiting = finishing = finishingDrain = false; index = 0; lastTick = started = entered = now; activeMs = 0; outputs = {};
        return true;
    }
    void stop(Fault cause = None) { outputs = {}; running = waiting = finishing = finishingDrain = false; fault = cause; completed = false; }
    bool advance(uint32_t now) {
        outputs = {}; waiting = false;
        if (index + 1 >= program.count) {
            finishing = true;
            finishingDrain = program.steps[index].kind == StepKind::Dry;
            if (finishingDrain) outputs.drainTogether(WasherMotorProfile::SpinDrainPwm);
            lastTick = entered = now;
            return true;
        }
        ++index;
        lastTick = entered = now; return true;
    }
    bool resume(uint32_t now, bool motionStopped = true) {
        if (!running || !waiting || !motionStopped || program.steps[index].kind != StepKind::Wait) return false;
        return advance(now);
    }
    void tick(uint32_t now, bool doorClosed, bool homeComplete, bool fillReady = true, bool fillReturned = true, bool motionStopped = true) {
        outputs = {};
        if (!running) return;
        if (finishing) {
            if (finishingDrain) outputs.drainTogether(WasherMotorProfile::SpinDrainPwm);
            if (motionStopped) {
                outputs = {}; running = finishing = finishingDrain = false; completed = true;
            }
            return;
        }
        const Step& step = program.steps[index];
        uint32_t delta = elapsed(now, lastTick); lastTick = now;
        if (!doorClosed && (step.kind != StepKind::Wait || !motionStopped)) { stop(DoorOpen); return; }
        if (step.kind != StepKind::Wait) {
            if (delta > 15000000u - activeMs) { stop(RunTimeout); return; }
            activeMs += delta;
        }
        uint32_t time = elapsed(now, entered);
        if (step.kind == StepKind::Home) {
            if (homeComplete) advance(now);
            else if (time >= step.duration) stop(HomeTimeout);
            return;
        }
        if (step.kind == StepKind::Wait) {
            // A manual pause never advances on a timer, including during loading jogs.
            waiting = true;
            return;
        }
        bool filling = step.kind == StepKind::FillA || step.kind == StepKind::FillB;
        if (filling && !fillReady) { entered = now; return; }
        if (time >= step.duration) {
            if (filling && !fillReturned) return;
            advance(now); return;
        }
        switch (step.kind) {
            case StepKind::FillA: outputs.a = true; outputs.overflow = WasherMotorProfile::FillOverflowPwm; break;
            case StepKind::FillB: outputs.b = true; outputs.overflow = WasherMotorProfile::FillOverflowPwm; break;
            case StepKind::Wash: outputs.rps = ((time / (step.reverseSeconds * 1000u)) % 2 ? -1 : 1) * step.rps; break;
            case StepKind::Drain: outputs.drainTogether(WasherMotorProfile::DrainPwm); break;
            case StepKind::Dry: outputs.rps = step.rps; outputs.drainTogether(WasherMotorProfile::SpinDrainPwm); break;
            default: break;
        }
    }
};
}
