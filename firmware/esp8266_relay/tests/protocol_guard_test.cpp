#include "../esp8266_relay/protocol_guard.h"
#include <cassert>
#include <iostream>

int main() {
  assert(allowLegacyUnidentified(true, 0, "delay_toggle"));
  assert(allowLegacyUnidentified(true, 0, "network_set"));
  assert(allowLegacyUnidentified(true, 0, "schedule_set"));
  assert(allowLegacyUnidentified(true, 0, "upgrade"));
  assert(!allowLegacyUnidentified(true, 0, "relay"));
  assert(!allowLegacyUnidentified(true, 0, "unknown"));
  assert(!allowLegacyUnidentified(false, 0, "delay_toggle"));
  assert(!allowLegacyUnidentified(true, 1, "delay_toggle"));
  assert(legacyMigrationState(false, 0, false, 0, true));
  assert(legacyMigrationState(true, 1, true, 0, true));
  assert(!legacyMigrationState(false, 0, false, 0, false));
  assert(!legacyMigrationState(false, 0, true, 0, true));
  assert(!legacyMigrationState(true, 2, true, 0, true));
  assert(!legacyMigrationState(true, 1, true, 3, true));
  // Old controllers work only during migration, and repeat IDs cannot toggle.
  assert(!rejectRelayCommand(true, true, false, 0, 0, 0, 100, true, false, true, true));
  assert(rejectRelayCommand(true, true, true, 0, 0, 0, 100, true, false, true, true));
  assert(rejectRelayCommand(false, true, false, 0, 0, 0, 100, true, true, false, false));
  assert(rejectRelayCommand(true, false, false, 0, 0, 0, 100, true, false, true, false));
  // A fresh V2 command can take over; a sequenced toggle is never accepted.
  assert(!rejectRelayCommand(true, true, false, 1, 0, 120, 100, true, false, true, false));
  assert(rejectRelayCommand(true, true, false, 1, 0, 120, 100, true, false, true, true));
  assert(rejectRelayCommand(false, true, false, 1, 1, 120, 100, true, true, false, false));
  assert(rejectRelayCommand(false, true, false, 2, 1, 90, 100, true, false, true, false));
  assert(rejectRelayCommand(false, true, false, 2, 1, 120, 0, false, false, true, false));
  // A new OFF is allowed even when its deadline elapsed; a stale OFF is not.
  assert(!rejectRelayCommand(false, true, false, 2, 1, 90, 100, true, true, false, false));
  assert(rejectRelayCommand(false, true, false, 1, 2, 120, 100, true, true, false, false));
  std::cout << "PROTOCOL_GUARD_OK 25 assertions\n";
}
