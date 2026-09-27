#pragma once
#include <cstdint>

namespace instrument {
struct JournalBudget {
    unsigned maximum = 0, observations = 0;
    static JournalBudget forBlocks(unsigned blocks) {
        if (blocks <= 32) return {};
        unsigned maximum = blocks - 32;
        if (maximum > 192) maximum = 192;
        return {maximum, maximum * 2 / 3};
    }
};
// Normally persist loss before eviction. A legacy completely full filesystem
// needs one verified ordinary sample removed first to make its ledger writable.
template<class Save, class Remove>
bool evictObservation(uint32_t next, bool present, bool recoverFull, Save save, Remove remove) {
    if (save(next)) return !present || remove();
    return recoverFull && present && remove() && save(next);
}
}
