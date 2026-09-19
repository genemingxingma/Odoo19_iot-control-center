#pragma once
#include <cstdint>

namespace instrument {
// Source baseline: supplied 2.0.2.0/public_var.h and 2.0.2.0.ino.
// PWM values are raw 8-bit duties, not voltages or measured flow rates.
struct WasherMotorProfile {
    static constexpr uint8_t DrainPwm = 150;
    static constexpr uint8_t SpinDrainPwm = 50;
    static constexpr uint8_t FillOverflowPwm = 255;
    static constexpr uint32_t StepsPerRevolution = 3200;
    static constexpr uint32_t HomeHz = 3200; // Original homing: 1 rev/s.
    static constexpr uint32_t PositionHz = HomeHz;
    static constexpr uint32_t MotionAcceleration = 3200; // 1 rev/s^2.
    // Original manual positioning used the homing speed and acceleration.
    // Commissioning may reduce this; a configured/calibrated value is required.
    static constexpr uint32_t LoadingHz = HomeHz;
    static constexpr uint32_t LoadingMinHz = 32, LoadingMaxHz = LoadingHz;
    static constexpr uint32_t LoadingAcceleration = MotionAcceleration;
};
}
