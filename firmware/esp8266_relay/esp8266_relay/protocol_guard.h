#pragma once
#include <stdint.h>
#include <string.h>

inline bool allowLegacyUnidentified(bool legacyEnabled, uint32_t sequence, const char* command) {
  if (!legacyEnabled || sequence != 0) { return false; }
  return strcmp(command, "network_set") == 0 || strcmp(command, "schedule_set") == 0
      || strcmp(command, "schedule_clear") == 0 || strcmp(command, "delay_toggle") == 0
      || strcmp(command, "delay_cancel") == 0 || strcmp(command, "upgrade") == 0;
}

inline bool legacyMigrationState(bool hasVersion, int version, bool hasSequence,
                                 uint32_t sequence, bool hasRelayState) {
  if (sequence != 0) { return false; }
  return hasVersion ? version == 1 : (!hasSequence && hasRelayState);
}

inline bool rejectRelayCommand(bool legacyEnabled, bool hasIdentity, bool legacyReplay,
                               uint32_t sequence, uint32_t lastSequence,
                               uint32_t expiresAt, uint32_t now, bool clockReady,
                               bool stopping, bool energizing, bool legacyToggle) {
  if (!hasIdentity || (sequence == 0 && (!legacyEnabled || legacyReplay))) {
    return true;
  }
  if (sequence > 0 && (sequence <= lastSequence || legacyToggle)) {
    return true;
  }
  if (stopping) {
    return false;
  }
  if (sequence == 0 && expiresAt == 0) {
    return false;  // Existing V1 controllers do not send an expiry.
  }
  return (clockReady && expiresAt <= now) || (energizing && !clockReady);
}
