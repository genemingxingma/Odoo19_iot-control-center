#pragma once
#include "control.hpp"

namespace instrument {
struct PumpTiming {
    uint32_t revision = 0;
    uint16_t a = 0, b = 0; // Seconds; zero means not calibrated, never a default dose.
    bool valid() const { return revision > 0 && revision <= 2147483647u && a <= 300 && b <= 300 && (a || b); }
    bool resolve(const Recipe& source, Recipe& result) const {
        if (!validRecipe(source) || source.schema != 2) return false;
        Recipe candidate = source;
        candidate.schema = 1;
        for (uint8_t i=0; i<candidate.count; ++i) {
            Step& step = candidate.steps[i];
            if (step.kind == StepKind::FillA || step.kind == StepKind::FillB) {
                uint16_t seconds = step.kind == StepKind::FillA ? a : b;
                if (!valid() || !seconds) return false;
                step.duration = uint32_t(seconds) * 1000u;
            }
        }
        if (!validRecipe(candidate)) return false;
        result = candidate;
        return true;
    }
};
}
