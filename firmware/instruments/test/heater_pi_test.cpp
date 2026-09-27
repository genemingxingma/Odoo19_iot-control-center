#include "control.hpp"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include <initializer_list>

using namespace instrument;

HeaterChannel prepared() {
    HeaterChannel heater;
    assert(heater.configureProtection(600, 1));
    return heater;
}

void exerciseModel(float liters, bool changeVolume) {
    HeaterChannel heater = prepared();
    double water = 25, deliveredWatts = 0;
    Probe probe{static_cast<float>(water), 0, true};
    assert(heater.arm(probe, 0));
    double minimumHeld = 100, maximumHeld = 0, maximum = water;
    // Synthetic water/heat-loss/element-lag model, not hardware acceptance.
    for (uint32_t now = 0; now <= 3600000; now += 10) {
        if (changeVolume && now == 1200000) {
            water = (2 * water + 3 * 25) / 5; liters = 5;
        }
        if (changeVolume && now == 2700000) liters = 2;
        if (now % 1000 == 0) probe = {static_cast<float>(std::round(water * 16) / 16), now, true};
        heater.tick(probe, now);
        assert(heater.enabled && heater.fault == None);
        assert(heater.powerPercent() >= 0 && heater.powerPercent() <= 100);
        deliveredWatts += ((heater.output ? 400 : 0) - deliveredWatts) * 0.01f / 5;
        water += (deliveredWatts - 2 * (water - 25)) * 0.01f / (4180 * liters);
        if (water > maximum) maximum = water;
        if (now >= 3000000) {
            if (water < minimumHeld) minimumHeld = water;
            if (water > maximumHeld) maximumHeld = water;
        }
    }
    assert(minimumHeld >= 41 && maximumHeld <= 43 && maximum <= 43);
    std::printf("Synthetic %.0f L%s: final %.2f C, holding %.2f..%.2f C\n",
        liters, changeVolume ? " variable-volume" : "", water, minimumHeld, maximumHeld);
}

int main() {
    HeaterChannel heater = prepared();
    Probe probe{39.5f, 0, true};
    assert(heater.arm(probe, 0));
    heater.tick(probe, 0);
    assert(heater.powerPercent() == 50 && heater.output);
    heater.tick(probe, 999); assert(heater.output);
    heater.tick(probe, 1000); assert(heater.output);
    heater.tick(probe, 1002); assert(!heater.output);
    // The one-second PI update adds 0.0833%, extending ON by one millisecond.
    probe.sampled = 2000; heater.tick(probe, 2000); assert(heater.output);
    heater.tick(probe, 3000); assert(heater.output);
    heater.tick(probe, 3006); assert(!heater.output);

    heater = prepared(); probe = {39.5f, 0, true};
    assert(heater.arm(probe, 0)); heater.tick(probe, 0);
    heater.pause(400); assert(!heater.output && heater.poweredMs == 400);
    probe.sampled = 100000;
    heater.tick(probe, 100000);
    assert(heater.powerPercent() == 50 && heater.poweredMs == 400);
    assert(heater.setTarget(38)); heater.tick(probe, 100000);
    assert(!heater.output && !heater.demand && heater.powerPercent() == 0);
    assert(heater.setTarget(42)); heater.tick(probe, 100000);
    assert(heater.output && heater.powerPercent() == 50 && heater.poweredMs == 0);
    heater.stop(); assert(!heater.output && !heater.demand && heater.powerPercent() == 0);
    assert(heater.arm(probe, 100000)); heater.tick(probe, 100000);
    assert(heater.powerPercent() == 50);

    // Far below target: no windup, and no-rise still trips at ten powered minutes.
    heater = prepared(); probe = {25, 0, true}; assert(heater.arm(probe, 0));
    for (uint32_t now = 0; now < 600000; now += 1000) {
        probe.sampled = now; heater.tick(probe, now);
        assert(heater.enabled && heater.output && heater.powerPercent() == 100);
    }
    probe.sampled = 600000; heater.tick(probe, 600000);
    assert(!heater.enabled && !heater.output && heater.fault == NoTemperatureRise);

    heater = prepared(); probe = {25, 0, true}; assert(heater.arm(probe, 0));
    for (uint32_t now = 0; now <= 300000; now += 1000) {
        probe.sampled = now; heater.tick(probe, now);
    }
    probe = {41, 301000, true}; heater.tick(probe, probe.sampled);
    assert(heater.powerPercent() > 20 && heater.powerPercent() < 21);

    // A constant holding temperature may request heat without a no-rise alarm.
    heater = prepared(); probe = {41.5f, 0, true}; assert(heater.arm(probe, 0));
    for (uint32_t now = 0; now <= 7200000; now += 100) {
        probe.sampled = now; heater.tick(probe, now);
        assert(heater.enabled && heater.fault == None && heater.poweredMs == 0);
    }
    probe = {43, 7200001, true}; heater.tick(probe, probe.sampled);
    assert(!heater.output && heater.powerPercent() == 0);
    probe = {41.5f, 7200002, true}; heater.tick(probe, probe.sampled);
    assert(heater.powerPercent() == 10);

    // Zero/short-pulse demand does not chatter the SSR.
    heater = prepared(); probe = {42, 0, true}; assert(heater.arm(probe, 0));
    heater.tick(probe, 0); assert(!heater.output && !heater.demand);
    probe = {41.99f, 1000, true}; heater.tick(probe, 1000);
    assert(!heater.output && !heater.demand && heater.powerPercent() < 1);
    probe.sampled = 2000; heater.tick(probe, 2000); assert(!heater.output);

    for (float bad : {55.0f, 85.0f, -127.0f, std::numeric_limits<float>::quiet_NaN()}) {
        heater = prepared(); probe = {25, 0, true}; assert(heater.arm(probe, 0)); heater.tick(probe, 0);
        probe = {bad, 1, true}; heater.tick(probe, 1);
        assert(!heater.output && !heater.enabled && heater.powerPercent() == 0);
    }
    heater = prepared(); probe = {39.5f, 0, true}; assert(heater.arm(probe, 0)); heater.tick(probe, 0);
    heater.tick(probe, 3001); assert(!heater.output && heater.fault == Sensor);
    heater = prepared(); probe = {39.5f, 0, true}; assert(heater.arm(probe, 0)); heater.tick(probe, 0);
    probe = {39.5f, 1200, false}; heater.tick(probe, 1200);
    assert(!heater.output && !heater.enabled && heater.fault == Sensor);

    // Window phase and actual ON-time survive the millisecond counter wrap.
    heater = prepared(); probe = {39.5f, 0xffffff00u, true};
    assert(heater.arm(probe, probe.sampled)); heater.tick(probe, probe.sampled);
    probe.sampled += 999; heater.tick(probe, probe.sampled); assert(heater.output);
    probe.sampled += 3; heater.tick(probe, probe.sampled); assert(!heater.output);
    assert(heater.poweredMs == 1002);
    probe.sampled += 998; heater.tick(probe, probe.sampled); assert(heater.output);
    assert(heater.poweredMs == 1002);

    exerciseModel(2, false);
    exerciseModel(5, false);
    exerciseModel(2, true);
    std::puts("FIXED_HEATER_PI_TESTS_OK");
}
