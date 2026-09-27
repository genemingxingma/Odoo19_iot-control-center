#include "heater_runtime.hpp"
#include "control.hpp"
#include "journal_budget.hpp"
#include <cassert>
#include <cstdio>
#include <vector>
#include <array>
using namespace instrument;
using Rom = std::array<uint8_t, 8>;
constexpr Rom bound = {0x28, 1, 2, 3, 4, 5, 6, 0x9e};
struct Bus {
    std::vector<Rom> devices;
    size_t cursor = 0;
    unsigned resets = 0;
    int reset() { ++resets; return !devices.empty(); }
    void reset_search() { cursor = 0; }
    bool search(uint8_t* out) {
        if (cursor == devices.size()) return false;
        std::memcpy(out, devices[cursor++].data(), 8); return true;
    }
    static uint8_t crc8(const uint8_t* data, uint8_t size) {
        uint8_t crc = 0;
        while (size--) {
            uint8_t value = *data++;
            for (unsigned bit = 0; bit < 8; ++bit) {
                uint8_t mix = (crc ^ value) & 1;
                crc >>= 1; if (mix) crc ^= 0x8c; value >>= 1;
            }
        }
        return crc;
    }
};
struct ProbeReader {
    bool connected = true, parasite = false;
    bool isConnected(const uint8_t*) const { return connected; }
    bool readPowerSupply(const uint8_t*) const { return parasite; }
};
int main() {
    Bus bus; ProbeReader sensor;
    assert(!scanHeaterProbe(bus, sensor).ready());
    bus.devices = {bound};
    auto inventory = scanHeaterProbe(bus, sensor);
    assert(inventory.count == 1 && inventory.presence && inventory.matches(bound.data()));
    // Recovery is a real search, not inferred from a cached temperature.
    assert(bus.resets == 2 && bus.cursor == 0);
    Rom other = bound; other[1] ^= 1; other[7] = Bus::crc8(other.data(), 7);
    bus.devices = {other};
    assert(scanHeaterProbe(bus, sensor).ready());
    assert(!scanHeaterProbe(bus, sensor).matches(bound.data()));
    bus.devices = {bound, other}; assert(!scanHeaterProbe(bus, sensor).ready());
    other[7] ^= 1; bus.devices = {other};
    assert(scanHeaterProbe(bus, sensor).crcError);
    bus.devices = {bound}; sensor.parasite = true;
    assert(!scanHeaterProbe(bus, sensor).ready());
    sensor.parasite = false;
    assert(scanHeaterProbe(bus, sensor).ready()); // Power flags must not be sticky.
    sensor.connected = false; assert(!scanHeaterProbe(bus, sensor).ready());
    sensor.connected = true; bus.devices.assign(12, bound);
    assert(scanHeaterProbe(bus, sensor).truncated);
    bus.devices.clear(); assert(!scanHeaterProbe(bus, sensor).presence);

    HeaterLoopGuard guard;
    guard.beat(100);
    assert(!guard.check(5100, guard.heartbeat)); // Idle operations cannot latch heat faults.
    assert(guard.maxGapMs == 5000 && !guard.triggered);
    guard.beat(5100); guard.powered = true; guard.phase = HeaterPhase::Control;
    assert(!guard.check(6100, guard.heartbeat));
    assert(guard.check(6101, guard.heartbeat));
    assert(!guard.powered && guard.triggered && guard.tripGapMs == 1001);
    assert(guard.tripPhase == HeaterPhase::Control);
    assert(!guard.check(6200, guard.heartbeat)); // One event per latch.
    guard = HeaterLoopGuard(); guard.powered = true;
    guard.beat(0xfffffff0u);
    assert(guard.check(0x00000400u, guard.heartbeat)); // Clock wrap remains protected.
    guard = HeaterLoopGuard(); guard.powered = true; guard.beat(110);
    assert(!guard.check(100, guard.heartbeat)); // An incoherent future sample is not a stall.
    guard.beat(100); guard.powered = false; guard.phase = HeaterPhase::Observation;
    assert(!guard.check(5000, guard.heartbeat));
    guard.beat(5000); guard.powered = true;
    assert(guard.check(6101, guard.heartbeat)); // Maintenance never disables later protection.

    HeaterChannel heater; heater.configureProtection(600, 1); heater.setTarget(37);
    Probe probe{20, 0, true}; assert(heater.arm(probe, 0)); heater.tick(probe, 0);
    assert(heater.output);
    heater.pause(1000); assert(!heater.output && heater.poweredMs == 1000);
    heater.pause(2000); assert(heater.poweredMs == 1000); // No invented powered time while saving.
    probe.sampled = 2000; heater.tick(probe, 2000); assert(heater.output);
    HeaterChannel defaults; heaterDefaults(defaults);
    assert(defaults.target == 42 && defaults.riseWindowMs == 600000 && defaults.minimumRise == 1);
    probe = {41, 0, true}; assert(defaults.arm(probe, 0)); defaults.tick(probe, 0); assert(defaults.output);
    probe = {42.5f, 1000, true}; defaults.tick(probe, 1000); assert(defaults.output);
    probe = {43, 2000, true}; defaults.tick(probe, 2000); assert(!defaults.output);
    probe = {41.5f, 3000, true}; defaults.tick(probe, 3000); assert(!defaults.output);
    probe = {41, 4000, true}; defaults.tick(probe, 4000); assert(defaults.output);
    probe = {0, 5000, false}; defaults.tick(probe, 5000);
    assert(!defaults.output && !defaults.enabled && defaults.fault == instrument::Sensor);
    assert(HeaterObservationMs == 3600000);
    auto budget = JournalBudget::forBlocks(125);
    assert(budget.maximum == 93 && budget.observations == 62);
    assert(JournalBudget::forBlocks(16).maximum == 0);
    assert(JournalBudget::forBlocks(4096).maximum == 192);
    std::vector<int> order;
    unsigned writes = 0;
    bool removed = false;
    assert(evictObservation(56, true, true,
        [&](uint32_t n) { assert(n == 56); order.push_back(1); return ++writes > 1; },
        [&]() { order.push_back(2); removed = true; return true; }));
    assert(removed && order == std::vector<int>({1, 2, 1}));
    removed = false;
    assert(!evictObservation(57, true, false, [](uint32_t) { return false; }, [&]() { removed = true; return true; }));
    assert(!removed); // Normal write errors cannot silently erase ordinary records.
    assert(!evictObservation(57, false, true, [](uint32_t) { return false; }, [&]() { removed = true; return true; }));
    assert(!removed); // There is no fallback that deletes a critical event.
    std::puts("Heater probe recovery and powered-loop watchdog tests passed");
}
