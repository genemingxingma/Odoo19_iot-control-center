#pragma once
#include <cstdint>
#include <cstring>
#include "control.hpp"

namespace instrument {
constexpr uint32_t HeaterObservationMs = 60u * 60u * 1000u;
inline void heaterDefaults(HeaterChannel& heater) {
    heater.setTarget(42); heater.configureProtection(600, 1);
}
struct HeaterProbeInventory {
    uint8_t count = 0, address[8] = {};
    bool presence = false, crcError = false, truncated = false;
    bool scratchpadValid = false, externalPower = false;
    bool ready() const {
        return count == 1 && address[0] == 0x28 && !crcError && !truncated &&
            scratchpadValid && externalPower;
    }
    bool matches(const uint8_t* expected) const {
        return ready() && std::memcmp(address, expected, 8) == 0;
    }
};

// One search pass supplies both count and ROM; a second search can disagree.
template<class Bus, class Sensor>
HeaterProbeInventory scanHeaterProbe(Bus& bus, Sensor& sensor) {
    HeaterProbeInventory result;
    result.presence = bus.reset() != 0;
    bus.reset_search();
    uint8_t address[8];
    while (bus.search(address)) {
        ++result.count;
        if (result.count == 1) std::memcpy(result.address, address, 8);
        if (Bus::crc8(address, 7) != address[7]) result.crcError = true;
        if (result.count > 8) { result.truncated = true; break; }
    }
    bus.reset_search();
    if (result.count == 1 && result.address[0] == 0x28 && !result.crcError) {
        result.scratchpadValid = sensor.isConnected(result.address);
        result.externalPower = result.scratchpadValid && !sensor.readPowerSupply(result.address);
    }
    return result;
}

enum class HeaterPhase : uint8_t { Idle, Usb, Probe, Control, FaultStorage, Display, Observation, Network };
struct HeaterLoopGuard {
    volatile uint32_t heartbeat = 0, maxGapMs = 0, tripGapMs = 0;
    volatile HeaterPhase phase = HeaterPhase::Idle, tripPhase = HeaterPhase::Idle;
    volatile bool powered = false, triggered = false;
    void beat(uint32_t now) { heartbeat = now; }
    bool check(uint32_t now, uint32_t sampledHeartbeat) {
        uint32_t gap = now - sampledHeartbeat;
        // Ignore an incoherent/future timestamp; ordinary uint32 wrap is valid.
        if (gap > 0x7fffffffu) return false;
        if (gap > maxGapMs) maxGapMs = gap;
        if (!powered || triggered || gap <= 1000) return false;
        tripGapMs = gap; tripPhase = phase; triggered = true; powered = false;
        return true;
    }
};
}
