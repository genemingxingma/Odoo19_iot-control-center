#include "runtime.hpp"
#include <SD.h>
#include <SPI.h>
#include <FastAccelStepper.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <esp_task_wdt.h>
#include "tjc_ui.hpp"
#include "program_catalog.hpp"
#include "pump_timing.hpp"

using namespace instrument;
constexpr const char* HARDWARE = "washer-esp32-4m-v1";
constexpr uint8_t ENABLE = 12, STEP = 13, DIRECTION = 15, HOME = 4, DOOR = 34;
constexpr uint8_t IN_A = 33, IN_B = 25, DRAIN = 27, OVERFLOW = 26, BUZZER = 21, SD_CS = 5;
constexpr uint32_t STEPS_PER_REV = WasherMotorProfile::StepsPerRevolution;
Washer washer; Probe temperature;
ProgramLibrary programLibrary;
PumpTiming pumpTiming, pumpDraft, runPumpTiming;
Startup startup;
WasherAuthorization authorization;
WifiDraft wifiDraft;
uint8_t librarySelection = 0;
uint8_t libraryPage = 0;
String catalogDigest;
String pendingCatalog, reviewedProgramId, reviewedCatalogDigest;
uint32_t reviewedRevision = 0;
uint32_t catalogCheckedAt = 0;
bool catalogInFlight = false;
bool discoveryInFlight = false;
runtime::Network network; runtime::Journal journal;
ExchangeSchedule exchangeSchedule;
OneWire oneWire(32); DallasTemperature sensors(&oneWire); DeviceAddress probeAddress;
FastAccelStepperEngine motion; FastAccelStepper* motor = nullptr;
QueueHandle_t requests = nullptr, responses = nullptr;
TaskHandle_t networkTaskHandle = nullptr;
volatile int catalogHttpStatus = 0;
bool commissioned = false, storage = false, networkReady = false, sdReady = false;
bool cleanupRequired = true;
bool inFlight = false, conversion = false, homeComplete = false, screenReady = false;
bool nativeScreenConfirmed = false;
bool probeAttached = false;
enum class RotorMode { Unconfigured, Open, Interlocked };
RotorMode rotorMode = RotorMode::Unconfigured;
bool openRotorLayout = false;
BalancedLoading loading;
bool rotorHomed = false, loadingCalibrated = false;
uint8_t loadingIndex = 255;
int32_t loadingOffset = 0;
uint32_t loadingHz = 0;
uint32_t conversionAt = 0, lastPoll = 0, lastDiscovery = 0, lastUi = 0, serialAt = 0;
String inFlightPath, inFlightId, runId, deviceId;
uint8_t homeIndex = 255, homePhase = 0, fillIndex = 255;
uint8_t fillPhase = 0;
uint32_t fillMoveAt = 0;
int32_t homeOffset = 0;
float lastSpeed = 0;
char serialLine[96]; uint8_t serialLength = 0; bool serialOverflow = false;
tjc::Display display;
uint32_t screenSeen = 0;
String uiMessage;

void encodeRecipe(JsonObject doc, const Recipe& p) {
    doc["schema"] = p.schema; doc["id"] = p.id; doc["label"] = p.label; doc["revision"] = p.revision;
    JsonArray steps = doc.createNestedArray("steps");
    const char* names[] = {"home", "fill_a", "fill_b", "wash", "drain", "dry", "wait"};
    for (uint8_t i=0; i<p.count; ++i) {
        const Step& s=p.steps[i]; JsonObject step=steps.createNestedObject();
        step["kind"]=names[static_cast<unsigned>(s.kind)];
        if (!(p.schema == 2 && (s.kind == StepKind::FillA || s.kind == StepKind::FillB))) step["duration_s"]=s.duration/1000;
        step["rps"]=s.rps; step["reverse_s"]=s.reverseSeconds;
        if (s.cycles) step["cycles"]=s.cycles;
    }
}
bool storeLibrary(ProgramLibrary& candidate, const String& digest = "") {
    DynamicJsonDocument doc(32768); doc["schema"]=1; doc["selected"]=candidate.selected;
    doc["catalog_digest"]=digest.length()?digest:catalogDigest;
    JsonArray programs=doc.createNestedArray("programs");
    for (uint8_t i=0; i<candidate.count; ++i) encodeRecipe(programs.createNestedObject(), candidate.items[i]);
    if (doc.overflowed()) return false;
    size_t expected=measureJson(doc);
    String text;
    if (expected>28672 || !text.reserve(expected)) return false;
    serializeJson(doc,text);
    if (text.length()!=expected || !runtime::atomicFile("/programs.json",text)) return false;
    programLibrary=std::move(candidate);
    if (programLibrary.count) washer.load(programLibrary.items[programLibrary.selected]);
    else { washer.program=Recipe(); washer.completed=false; }
    if (digest.length()) catalogDigest=digest;
    return true;
}
bool loadLibrary() {
    ProgramLibrary candidate;
    if (LittleFS.exists("/programs.json")) {
        DynamicJsonDocument doc(32768);
        if (deserializeJson(doc,runtime::readFile("/programs.json",28672)) || doc["schema"]!=1 || !doc["programs"].is<JsonArray>() || !doc["selected"].is<uint8_t>()) return false;
        JsonArray list=doc["programs"];
        if (list.size()>ProgramLibrary::Capacity) return false;
        for (JsonVariant p:list) {
            Recipe item;
            if (!runtime::parseRecipe(p,item) || candidate.find(item.id)>=0 || !candidate.put(item)) return false;
        }
        uint8_t selected=doc["selected"];
        if ((candidate.count && !candidate.select(selected)) || (!candidate.count && selected)) return false;
        programLibrary=candidate;
        catalogDigest=doc["catalog_digest"]|"";
        return !candidate.count || washer.load(candidate.items[selected]);
    }
    if (!LittleFS.exists("/recipe.json")) return true;
    DynamicJsonDocument doc(8192); Recipe old;
    if (deserializeJson(doc,runtime::readFile("/recipe.json")) || !runtime::parseRecipe(doc.as<JsonVariantConst>(),old) || !candidate.put(old)) return false;
    return storeLibrary(candidate); // Preserve the original single-program file.
}
bool idleForSettings() { return !washer.running && !startup.active() && (!motor || !motor->isRunning()); }
void encodePumpTiming(JsonObject value, const PumpTiming& timing) {
    value["revision"] = timing.revision; value["a_s"] = timing.a; value["b_s"] = timing.b;
}
bool decodePumpTiming(JsonVariantConst value, PumpTiming& result) {
    if (!value["revision"].is<uint32_t>() || !value["a_s"].is<uint16_t>() || !value["b_s"].is<uint16_t>()) return false;
    PumpTiming candidate{value["revision"], value["a_s"], value["b_s"]};
    if (!candidate.valid()) return false;
    result = candidate; return true;
}
void loadPumpTiming() {
    DynamicJsonDocument d(256);
    if (LittleFS.exists("/pump-timing.json") &&
        (deserializeJson(d, runtime::readFile("/pump-timing.json", 256)) || d["schema"] != 1 ||
         !decodePumpTiming(d.as<JsonVariantConst>(), pumpTiming))) {
        pumpTiming = {}; uiMessage = "Fill-time settings are invalid. Set Buffer A and B again.";
    }
}
void savePumpTiming() {
    if (pumpTiming.valid() && pumpTiming.a == pumpDraft.a && pumpTiming.b == pumpDraft.b) {
        uiMessage = "Already saved. Pumps remain off."; return;
    }
    if (!storage || !idleForSettings() || pumpTiming.revision >= 2147483647u) { uiMessage = "Cannot save pump settings now."; return; }
    PumpTiming candidate = pumpDraft; candidate.revision = pumpTiming.revision + 1;
    if (!candidate.valid()) { uiMessage = "Set at least one pump: 1 to 300 seconds."; return; }
    DynamicJsonDocument d(256); encodePumpTiming(d.to<JsonObject>(), candidate); d["schema"] = 1;
    String text; serializeJson(d, text);
    if (d.overflowed() || !runtime::atomicFile("/pump-timing.json", text)) { uiMessage = "Save failed. Previous pump settings kept."; return; }
    pumpTiming = pumpDraft = candidate; uiMessage = "Saved on this device. Pumps remain off.";
}
bool setCleanupRequired(bool required) {
    if (!storage) return false;
    if (required) {
        if (!runtime::atomicFile("/cleanup-required.json", "{\"required\":true}")) { journal.healthy=false; return false; }
    } else if (LittleFS.exists("/cleanup-required.json") && !LittleFS.remove("/cleanup-required.json")) {
        journal.healthy=false; return false;
    }
    cleanupRequired=required; return true;
}
bool reviewedProgramStillCurrent() {
    return reviewedProgramId == washer.program.id && reviewedRevision == washer.program.revision && reviewedCatalogDigest == catalogDigest;
}
void openWifi() {
    wifiDraft.clear();
    strlcpy(wifiDraft.ssid,network.ssid.c_str(),sizeof(wifiDraft.ssid));
    strlcpy(wifiDraft.password,network.password.c_str(),sizeof(wifiDraft.password));
    display.page=6; uiMessage="Tap fields to edit, then SAVE / CONNECT. Blank password: open network.";
}
void saveWifi() {
    if (!storage || !idleForSettings() || inFlight) { uiMessage="Busy. Wait, then retry."; return; }
    if (!wifiDraft.valid()) { uiMessage="Enter SSID and an 8-63 character password, or 64 hex digits."; return; }
    DynamicJsonDocument doc(512); doc["ssid"]=wifiDraft.ssid; doc["password"]=wifiDraft.password;
    String text; serializeJson(doc,text);
    if (!runtime::atomicFile("/wifi.json",text)) { uiMessage="Could not save. Previous Wi-Fi settings kept."; return; }
    network.ssid=wifiDraft.ssid; network.password=wifiDraft.password;
    WiFi.persistent(false); WiFi.disconnect(); WiFi.mode(WIFI_STA);
    WiFi.begin(network.ssid.c_str(),network.password.c_str());
    configTime(0,0,"pool.ntp.org");
    uiMessage="Saved. Connecting to the 2.4 GHz network...";
}

bool motionAllowed() {
    return rotorMode == RotorMode::Open || (rotorMode == RotorMode::Interlocked && digitalRead(DOOR) == LOW);
}
void setDrainOutputs(uint8_t drain, uint8_t overflow) {
    ledcWrite(0, drain); ledcWrite(1, overflow);
}
void outputsOff() {
    digitalWrite(IN_A, LOW); digitalWrite(IN_B, LOW);
    setDrainOutputs(0, 0); digitalWrite(ENABLE, LOW);
    if (motor) motor->forceStop();
    lastSpeed = 0; loading.reset(); loadingIndex = 255; rotorHomed = false;
}
void hmi(const String& command) {
    Serial2.print(command); Serial2.write(0xff); Serial2.write(0xff); Serial2.write(0xff);
}
const char* stateName() {
    if (washer.fault != None || !journal.healthy) return "fault";
    if (!authorization.allowed()) return "uncommissioned";
    return startup.active() ? "running" : washer.waiting ? "waiting" : washer.running ? "running" : "idle";
}
void snapshot(JsonDocument& d) {
    journal.envelope(d);
    JsonObject s = d.createNestedObject("status");
    s["state"] = stateName(); s["firmware"] = runtime::version; s["hardware"] = HARDWARE;
    s["device_id"] = deviceId;
    s["commissioned"] = commissioned; s["field_test"] = authorization.fieldTest;
    s["loading_calibrated"] = loadingCalibrated;
    s["recipe_schema"] = 2;
    encodePumpTiming(s.createNestedObject("pump_timing"), pumpTiming);
    s["build"] = "IMYTESTFW1:washer:washer-esp32-4m-v1:" INSTRUMENT_STRING_VALUE(INSTRUMENT_FIRMWARE_VERSION) ":END";
    s["step"] = washer.index; s["steps"] = washer.program.count;
    s["remaining_s"] = washer.running && !washer.waiting ? max(0L, static_cast<long>(washer.program.steps[washer.index].duration - min(washer.program.steps[washer.index].duration, elapsed(millis(), washer.entered))) / 1000) : 0;
    bool fresh = temperature.valid && elapsed(millis(), temperature.sampled) <= 3000;
    s["temperature_valid"] = fresh;
    if (fresh) s["temperature"] = temperature.value;
    s["fault"] = washer.fault; s["run_id"] = runId;
    s["rotor_mode"] = rotorMode == RotorMode::Open ? "open" : rotorMode == RotorMode::Interlocked ? "interlocked" : "unconfigured";
    if (rotorMode == RotorMode::Interlocked) s["door_closed"] = digitalRead(DOOR) == LOW;
    if (washer.waiting && loading.currentSlot() != BalancedLoading::Unknown) s["loading_slot"] = loading.currentSlot() + 1;
    if (washer.waiting) s["loading_target_slot"] = loading.nextSlot() + 1;
    s["loading_motion"] = loading.active;
    s["drain_pwm"] = washer.outputs.drain; s["overflow_pwm"] = washer.outputs.overflow;
    s["initialization"] = static_cast<unsigned>(startup.phase);
    if (startup.active()) s["drain_pwm"] = s["overflow_pwm"] = startup.drain();
    s["catalog_sync"]=1; s["catalog_digest"]=catalogDigest; s["program_count"]=programLibrary.count;
    s["cleanup_required"]=cleanupRequired; s["journal_pending"]=journal.pending(); s["journal_free"]=journal.criticalFree();
}
bool logEvent(const char* event, const char* message = "") {
    if (!runId.length()) return true;
    DynamicJsonDocument d(3072); snapshot(d);
    JsonObject log = d.createNestedObject("log");
    log["run_id"] = runId; log["recipe_id"] = washer.program.id;
    log["revision"] = washer.program.revision; log["step"] = washer.index;
    log["event"] = event; log["message"] = message;
    encodePumpTiming(log.createNestedObject("pump_timing"), runPumpTiming);
    bool terminal=!strcmp(event,"completed") || !strcmp(event,"aborted") || !strcmp(event,"fault") || !strcmp(event,"power_loss");
    if (!journal.save(d,false,terminal)) { washer.stop(Storage); outputsOff(); return false; }
    return true;
}
void stopRun(Fault fault, const char* reason) {
    startup.stop();
    bool wasRunning = washer.running;
    if (!setCleanupRequired(true)) fault=Storage;
    washer.stop(fault); outputsOff(); homeComplete = false; homeIndex = fillIndex = 255;
    if (wasRunning && logEvent(fault == None ? "aborted" : "fault", reason)) {
        LittleFS.remove("/run.json"); runId = "";
    }
}
bool saveRunMarker() {
    DynamicJsonDocument d(512); d["run_id"] = runId; d["recipe_id"] = washer.program.id; d["revision"] = washer.program.revision;
    encodePumpTiming(d.createNestedObject("pump_timing"), runPumpTiming);
    String text; serializeJson(d, text); return runtime::atomicFile("/run.json", text);
}
void startRun() {
    if (!idleForSettings() || !programLibrary.count) { uiMessage="Select a program first."; return; }
    const Recipe& source = programLibrary.items[programLibrary.selected];
    Recipe resolved;
    if (source.schema != 2) { uiMessage="Legacy program. Sync from IoT Center."; return; }
    if (!pumpTiming.resolve(source, resolved)) { uiMessage="Set Buffer A and B fill times in Settings."; return; }
    if (startup.phase != Startup::Ready) { uiMessage="Wait for automatic startup preparation to finish."; return; }
    if (cleanupRequired) { uiMessage="Initialization cleanup is required before starting."; return; }
    if (!screenReady || !authorization.allowed() || !journal.healthy || !motor) { uiMessage = "Start blocked: check setup and log storage."; return; }
    unsigned waits=0; for (uint8_t i=0;i<washer.program.count;++i) if (washer.program.steps[i].kind==StepKind::Wait) ++waits;
    if (!journal.reserveCritical(unsigned(washer.program.count)+waits*2+6)) { uiMessage="Start blocked: upload or service the full event log."; return; }
    if (!washer.load(resolved)) { uiMessage="Program could not be prepared."; return; }
    runPumpTiming = pumpTiming;
    if (!setCleanupRequired(true)) { uiMessage="Start blocked: cleanup state could not be saved."; return; }
    if (motor->isRunning() || !washer.start(millis(), authorization.allowed(), motionAllowed())) { uiMessage = "Start blocked: check setup, program and active fault."; return; }
    uiMessage = "";
    runId = runtime::randomId(); homeIndex = fillIndex = 255; homeComplete = rotorHomed = false;
    if (!saveRunMarker() || !logEvent("started")) { washer.stop(Storage); outputsOff(); }
    else if (!temperature.valid) logEvent("sensor_warning", "Liquid temperature unavailable; timed program continues");
}
void sdUpdate() {
    if (!authorization.configured() || !idleForSettings() || inFlight) { uiMessage = "Update blocked. Stop first; wait and retry."; return; }
    outputsOff();
    if (!sdReady) sdReady = SD.begin(SD_CS);
    if (!sdReady) { uiMessage = "SD card unavailable. Insert the ESP32 SD card."; return; }
    File manifestFile = SD.open("/imytest-update/manifest.json");
    if (!manifestFile || manifestFile.size() > 2048) { uiMessage = "SD update manifest is missing or too large."; return; }
    runtime::Manifest m;
    if (!runtime::manifest(manifestFile.readString(), "washer", HARDWARE, m)) { uiMessage = "Update rejected: signature, board or version."; return; }
    manifestFile.close(); File binary = SD.open("/imytest-update/firmware.bin");
    if (!binary || binary.size() != m.size) { uiMessage = "SD firmware is missing or has the wrong size."; return; }
    esp_task_wdt_delete(nullptr);
    bool ok = runtime::install(binary, m); binary.close();
    esp_task_wdt_add(nullptr);
    if (ok) ESP.restart();
    // Keep the package for diagnosis. Version checks prevent repeat installation.
    uiMessage = "Update rejected; firmware unchanged";
}
void nextLoadingPosition() {
    if (!screenReady || !authorization.allowed() || !journal.healthy || !motionAllowed() || !motor || display.page != 4) return;
    if (!washer.running || !washer.waiting || loading.active || motor->isRunning() || !loadingCalibrated || !rotorHomed || loadingIndex != washer.index) return;
    digitalWrite(IN_A, LOW); digitalWrite(IN_B, LOW); setDrainOutputs(0, 0);
    int32_t position = motor->getCurrentPosition() % static_cast<int32_t>(STEPS_PER_REV);
    if (position < 0) position += STEPS_PER_REV;
    loading.prime(position, loadingOffset, true, true);
    if (loading.currentSlot() != BalancedLoading::Unknown && slotDelta(position, loading.currentSlot(), loadingOffset, STEPS_PER_REV) != 0) {
        stopRun(RunTimeout, "Loading reference changed; restart and home"); return;
    }
    String message = "Loading move requested: slot " + String(loading.nextSlot() + 1) + "; program remains paused";
    if (!logEvent("waiting", message.c_str())) return;
    motor->setCurrentPosition(position);
    if (!loading.start(millis(), position, loadingOffset, loadingHz, true, true, true)) return;
    motor->setSpeedInHz(loadingHz); motor->setAcceleration(WasherMotorProfile::LoadingAcceleration); lastSpeed = 0;
    if (motor->move(loading.distance) != MOVE_OK) stopRun(RunTimeout, "Loading position command rejected");
}
void saveLoadingReference();
bool commandSeconds(const char* command, const char* prefix, uint16_t& result) {
    const size_t length = strlen(prefix);
    if (strncmp(command, prefix, length)) return false;
    const char* value = command + length;
    char* end = nullptr;
    unsigned long parsed = strtoul(value, &end, 10);
    if (!value[0] || !end || *end || parsed > 300) return true;
    result = static_cast<uint16_t>(parsed);
    return true;
}
void localCommand(const char* command) {
    if (!strcmp(command, "UI|BOOT|4")) {
        if (washer.running || startup.active()) stopRun(Storage, "Operator screen restarted");
        nativeScreenConfirmed = true;
        display.invalidate();
        screenReady = true;
        screenSeen = millis();
        return;
    }
    if (!strcmp(command, "UI|HELLO|4")) {
        // During a paired upgrade the screen can finish booting while the
        // controller is still held in ROM, so its one-shot BOOT frame is lost.
        // Accept the versioned heartbeat only during a short, idle controller
        // startup window. Independent screen restarts during operation still
        // arrive as BOOT and take the fail-safe stop path above.
        if (!nativeScreenConfirmed) {
            if (millis() > 30000 || washer.running || startup.active()) return;
            nativeScreenConfirmed = true;
            display.invalidate();
        }
        if (!screenReady) {
            display.invalidate();
        }
        screenReady = true;
        screenSeen = millis();
        return;
    }
    // STOP remains the only command accepted independently of the current page.
    if (!strcmp(command, "UI|STOP") && nativeScreenConfirmed) {
        stopRun(None, "Stopped locally");
        display.page = tjc::Overview;
        display.dirty = true;
        return;
    }
    if (!screenReady || !nativeScreenConfirmed) return;
    screenSeen = millis();

    if (!strcmp(command, "UI|HOME")) {
        if (idleForSettings()) {
            // A completed run remains visible until the operator explicitly
            // acknowledges it by returning home.
            washer.completed = false;
            display.page = tjc::Overview;
            uiMessage = "";
        }
    } else if (!strcmp(command, "UI|SETTINGS")) {
        if (idleForSettings()) display.page = tjc::Settings;
    } else if (!strcmp(command, "UI|PROGRAMS")) {
        if (idleForSettings()) {
            librarySelection = programLibrary.selected;
            libraryPage = librarySelection / 3;
            display.page = tjc::Programs;
        }
    } else if (!strncmp(command, "UI|PROGRAM|", 11) && idleForSettings()) {
        int choice = command[11] - '0';
        if (command[11] >= '0' && command[11] <= '2' && !command[12] &&
            libraryPage * 3 + choice < programLibrary.count)
            librarySelection = libraryPage * 3 + choice;
    } else if (!strcmp(command, "UI|PROGRAM_PREV") && idleForSettings()) {
        if (programLibrary.count)
            librarySelection = librarySelection ? librarySelection - 1 : programLibrary.count - 1;
        libraryPage = librarySelection / 3;
    } else if (!strcmp(command, "UI|PROGRAM_NEXT") && idleForSettings()) {
        if (programLibrary.count)
            librarySelection = (librarySelection + 1) % programLibrary.count;
        libraryPage = librarySelection / 3;
    } else if (!strcmp(command, "UI|PROGRAM_SELECT") && idleForSettings()) {
        if (librarySelection < programLibrary.count) {
            ProgramLibrary copy = programLibrary;
            if (copy.select(librarySelection) && storeLibrary(copy)) {
                display.page = tjc::Overview;
                uiMessage = "Program selected. Review before starting.";
            } else {
                journal.healthy = false;
                uiMessage = "Program selection could not be saved.";
            }
        }
    } else if (!strcmp(command, "UI|REVIEW") && idleForSettings()) {
        uiMessage = "";
        reviewedProgramId = washer.program.id;
        reviewedRevision = washer.program.revision;
        reviewedCatalogDigest = catalogDigest;
        display.page = tjc::Review;
    } else if (!strcmp(command, "UI|START")) {
        if (display.page != tjc::Review) uiMessage = "Review the selected program before starting.";
        else if (reviewedProgramStillCurrent()) {
            startRun();
            if (washer.running) display.page = tjc::Overview;
        } else uiMessage = "Program changed. Review it again before starting.";
    } else if (!strcmp(command, "UI|CONTINUE") && motionAllowed()) {
        if (!loading.active && motor && washer.resume(millis(), !motor->isRunning())) {
            loading.reset(); loadingIndex = 255; logEvent("continued"); display.page = tjc::Overview;
        }
    } else if (!strcmp(command, "UI|LOAD_ACTION")) {
        if (loadingCalibrated) nextLoadingPosition();
        else saveLoadingReference();
    } else if (!strcmp(command, "UI|WIFI") && idleForSettings()) {
        openWifi();
    } else if (!strncmp(command, "UI|WIFI_SSID|", 13) && idleForSettings()) {
        strlcpy(wifiDraft.ssid, command + 13, sizeof(wifiDraft.ssid));
    } else if (!strncmp(command, "UI|WIFI_PASS|", 13) && idleForSettings()) {
        strlcpy(wifiDraft.password, command + 13, sizeof(wifiDraft.password));
    } else if (!strcmp(command, "UI|WIFI_SAVE") && idleForSettings()) {
        saveWifi();
    } else if (!strcmp(command, "UI|WIFI_CANCEL") && idleForSettings()) {
        wifiDraft.clear(); uiMessage = ""; display.page = tjc::Settings;
    } else if (!strcmp(command, "UI|PUMP") && idleForSettings()) {
        pumpDraft = pumpTiming; display.page = tjc::PumpTimes;
        uiMessage = "Tap left for A, right for B. Zero means not set.";
    } else if (commandSeconds(command, "UI|PUMP_A|", pumpDraft.a) && idleForSettings()) {
        uiMessage = "Unsaved device-local calibration.";
    } else if (commandSeconds(command, "UI|PUMP_B|", pumpDraft.b) && idleForSettings()) {
        uiMessage = "Unsaved device-local calibration.";
    } else if (!strcmp(command, "UI|PUMP_SAVE") && idleForSettings()) {
        savePumpTiming();
    } else if (!strcmp(command, "UI|PUMP_CANCEL") && idleForSettings()) {
        pumpDraft = pumpTiming; uiMessage = ""; display.page = tjc::Settings;
    } else if (!strcmp(command, "UI|MAINTENANCE") && idleForSettings()) {
        display.page = tjc::Maintenance;
    } else if (!strcmp(command, "UI|RESET") && !washer.running && motionAllowed()) {
        bool hadFault = washer.fault != None;
        washer.fault = None;
        uiMessage = hadFault ? "Fault reset. Inspect the machine before starting." : "No active fault.";
    } else if (!strcmp(command, "UI|SD_CONFIRM") && idleForSettings()) {
        display.page = tjc::SdConfirm;
    } else if (!strcmp(command, "UI|UPDATE_SD") && idleForSettings()) {
        sdUpdate(); display.page = tjc::Overview;
    } else if (!strcmp(command, "UI|BACK") && idleForSettings()) {
        if (display.page == tjc::SdConfirm)
            display.page = tjc::Maintenance;
        else if (display.page == tjc::Wifi || display.page == tjc::PumpTimes ||
                 display.page == tjc::Maintenance)
            display.page = tjc::Settings;
        else display.page = tjc::Overview;
        uiMessage = "";
    }
    display.dirty = true;
}
void saveLoadingReference() {
    if (!authorization.allowed() || !screenReady || !journal.healthy || !washer.running || !washer.waiting ||
        !rotorHomed || washer.fault != None || !motor || motor->isRunning() || loading.active ||
        !motionAllowed() || digitalRead(IN_A) || digitalRead(IN_B) ||
        ledcRead(0) || ledcRead(1)) {
        uiMessage = "Pause at a loading step first. Rotor and pumps must be stopped.";
        return;
    }
    DynamicJsonDocument config(1024);
    if (deserializeJson(config, runtime::readFile("/hardware.json", 1024))) {
        uiMessage = "Hardware settings could not be read."; return;
    }
    int32_t position = motor->getCurrentPosition() % static_cast<int32_t>(STEPS_PER_REV);
    if (position < 0) position += STEPS_PER_REV;
    config["loading_offset_steps"] = position;
    config["loading_index_hz"] = WasherMotorProfile::LoadingHz;
    config["loading_calibrated"] = true;
    String text; serializeJson(config, text);
    if (config.overflowed() || !runtime::atomicFile("/hardware.json", text)) {
        uiMessage = "Could not save loading reference. Previous settings kept."; return;
    }
    loadingOffset = position; loadingHz = WasherMotorProfile::LoadingHz;
    loadingCalibrated = true; loading.reset();
    logEvent("waiting", "Loading slot 1 confirmed locally and saved");
    uiMessage = "Loading slot 1 saved. Check opposite-pair positioning during a wait.";
}
void touchCommand(int button) {
    if (button == 2) { stopRun(None, "Stopped locally"); wifiDraft.clear(); display.page = 0; }
    else if (!screenReady || button < 0 || !display.acceptsAction(millis())) return;
    else if (display.page >= 5) {
        if (!idleForSettings() && !(display.page == 8 && washer.running && washer.waiting && motor && !motor->isRunning() && !loading.active)) return;
        if (display.page == 5) {
            if (button>=10 && button<13 && libraryPage*3+button-10<programLibrary.count) librarySelection=libraryPage*3+button-10;
            else if (button==0 && librarySelection<programLibrary.count) {
                ProgramLibrary copy=programLibrary; copy.select(librarySelection);
                if (storeLibrary(copy)) display.page=0;
                else { journal.healthy=false; uiMessage="Program selection could not be saved."; }
            } else if (button==1) display.page=0;
            else if (button==3 && libraryPage) --libraryPage;
            else if (button==4 && (libraryPage+1)*3<programLibrary.count) ++libraryPage;
        } else if (display.page == 8) {
            if (button == 0) { saveLoadingReference(); if (loadingCalibrated) display.page = 4; }
            else if (button == 1) display.page = 4;
        } else if (display.page == 10) {
            if (button == 0) savePumpTiming();
            else if (button == 1) { display.page=2; uiMessage=""; }
            else if (button >= 10 && button < 18) {
                uint16_t& seconds = button < 14 ? pumpDraft.a : pumpDraft.b;
                const int changes[] = {-10, -1, 1, 10};
                seconds = max(0, min(300, int(seconds) + changes[(button-10)%4]));
                uiMessage="Unsaved A/B times. Save Fill Times stores both on this washer.";
            }
        } else if (display.page == 6) {
            if (button==0) saveWifi();
            else if (button==1) { wifiDraft.clear(); uiMessage=""; display.page=2; }
            else if (button==3 || button==4) { wifiDraft.beginEdit(button==4); display.page=7; }
        } else if (display.page == 7) {
            if (button>=10 && button<50) wifiDraft.append(WifiDraft::keys(wifiDraft.keyboard)[button-10]);
            else if (button==50) wifiDraft.backspace();
            else if (button==51) wifiDraft.keyboard=wifiDraft.keyboard==1?0:1;
            else if (button==52) wifiDraft.keyboard=wifiDraft.keyboard==2?0:2;
            else if (button==53) wifiDraft.append(' ');
            else if (button==0 || button==1) {
                wifiDraft.endEdit(button==0); display.page=6;
                uiMessage=button==0?"Edit kept. Tap SAVE / CONNECT to apply.":"Edit cancelled. Wi-Fi settings unchanged.";
            }
        }
    }
    else if (button==3 && idleForSettings()) {
        if (display.page==0) display.page=2;
        else if (display.page==2) openWifi();
    }
    else if (button==4 && display.page==2 && idleForSettings()) display.page=9;
    else if (button==5 && display.page==2 && idleForSettings()) display.page=0;
    else if (button==6 && display.page==2 && idleForSettings()) { pumpDraft=pumpTiming; display.page=10; uiMessage="Set measured fill times. Zero = NOT SET."; }
    else if (button == 0) {
        if ((display.page == 0 || display.page == 4) && washer.waiting) localCommand("UI|CONTINUE");
        else if (display.page == 0 && idleForSettings()) {
            uiMessage="";
            reviewedProgramId=washer.program.id; reviewedRevision=washer.program.revision; reviewedCatalogDigest=catalogDigest; display.page = 1;
        }
        else if (display.page == 1) {
            if (!reviewedProgramStillCurrent()) uiMessage="Program changed. Return and review the current version.";
            else { startRun(); if (washer.running) display.page = 0; }
        }
        else if (display.page == 2) {
            bool hadFault=washer.fault!=None;
            localCommand("UI|RESET");
            uiMessage=washer.fault!=None?"Fault remains. Check device before resetting.":hadFault?"Fault reset. Inspect the machine before starting.":"No fault to reset.";
        }
        else if (display.page == 3) { sdUpdate(); display.page = 0; }
    } else if (button == 1) {
        if (display.page == 4) {
            if (!loadingCalibrated && authorization.allowed() && rotorHomed && washer.running && washer.waiting && motor && !motor->isRunning() && !loading.active) display.page = 8;
            else nextLoadingPosition();
        }
        else if (display.page == 0 && idleForSettings()) { librarySelection=programLibrary.selected; libraryPage=librarySelection/3; display.page = 5; }
        else if (display.page == 2) display.page = 3;
        else if (display.page != 4) display.page = 0;
    }
    display.dirty = true;
}
void serialTick() {
    if (serialLength && elapsed(millis(), serialAt) > 1000) { serialLength = 0; serialOverflow = false; }
    unsigned budget = 128;
    while (Serial2.available() && budget--) {
        char c = Serial2.read(); serialAt = millis();
        // Native pages send newline-delimited ASCII commands. Ignore all binary
        // bytes, including legacy coordinate packets, before line assembly.
        if (static_cast<uint8_t>(c) < 32 && c != '\n' && c != '\r') {
            serialLength = 0; serialOverflow = false; continue;
        }
        if (c == '\n') {
            if (!serialOverflow) { serialLine[serialLength] = 0; localCommand(serialLine); }
            serialLength = 0; serialOverflow = false;
        } else if (c != '\r') {
            if (serialLength < sizeof(serialLine)-1 && static_cast<uint8_t>(c) >= 32 && c < 127) serialLine[serialLength++] = c;
            else serialOverflow = true;
        }
    }
}
void usbDiagnostics() {
    static char input[16] = {};
    static uint8_t length = 0;
    static bool overflow = false;
    static uint32_t lastReply = 0;
    unsigned budget = 32;
    while (Serial.available() && budget--) {
        char c = Serial.read();
        if (c == '\r') continue;
        if (c != '\n') {
            if (length < sizeof(input)-1 && c >= 32 && c < 127) input[length++] = c;
            else overflow = true;
            continue;
        }
        input[length] = 0;
        bool requested = !overflow && !strcmp(input,"STATUS");
        length = 0; overflow = false;
        if (!requested || elapsed(millis(),lastReply) < 1000) continue;
        lastReply = millis();
        // Read-only USB diagnostics: no credentials, provisioning or motion commands.
        StaticJsonDocument<2560> d;
        d["firmware"] = runtime::version; d["hardware"] = HARDWARE;
        d["device_id"] = deviceId;
        d["boot"] = journal.boot; d["uptime_ms"] = millis(); d["epoch"] = time(nullptr);
        d["commissioned"] = commissioned; d["state"] = stateName();
        d["field_test"] = authorization.fieldTest;
        d["loading_calibrated"] = loadingCalibrated; d["home_input"] = digitalRead(HOME);
        d["recipe_schema"] = 2; encodePumpTiming(d.createNestedObject("pump_timing"), pumpTiming);
        d["rotor_homed"] = rotorHomed; d["home_offset_steps"] = homeOffset;
        d["loading_offset_steps"] = loadingOffset; d["initialization"] = static_cast<unsigned>(startup.phase);
        d["open_rotor"] = openRotorLayout;
        d["storage"] = storage; d["journal_healthy"] = journal.healthy;
        d["screen_ready"] = screenReady; d["screen_age_ms"] = elapsed(millis(),screenSeen);
        d["screen_page"] = display.page; d["screen_busy"] = display.busy();
        d["wifi_connected"] = WiFi.status() == WL_CONNECTED;
        if (WiFi.status() == WL_CONNECTED) { d["ip"] = WiFi.localIP().toString(); d["rssi"] = WiFi.RSSI(); }
        d["platform_configured"] = networkReady; d["sync_in_flight"] = catalogInFlight;
        d["catalog_http_status"] = catalogHttpStatus;
        d["free_heap"] = ESP.getFreeHeap(); d["minimum_heap"] = ESP.getMinFreeHeap();
        if (networkTaskHandle) d["network_stack_free"] = uxTaskGetStackHighWaterMark(networkTaskHandle);
        d["catalog_digest"] = catalogDigest; d["program_count"] = programLibrary.count;
        d["cleanup_required"] = cleanupRequired; d["journal_pending"] = journal.pending(); d["journal_free"] = journal.criticalFree();
        d["selected_program"] = washer.program.id; d["selected_revision"] = washer.program.revision;
        d["enable_pin"] = digitalRead(ENABLE); d["inlet_a_pin"] = digitalRead(IN_A); d["inlet_b_pin"] = digitalRead(IN_B);
        d["drain_pwm"] = ledcRead(0); d["overflow_pwm"] = ledcRead(1);
        d["motor_running"] = motor && motor->isRunning();
        d["temperature_valid"] = temperature.valid;
        if (temperature.valid) d["temperature"] = temperature.value;
        Serial.print("IOT_STATUS "); serializeJson(d,Serial); Serial.println();
    }
}
void remoteCommand(JsonObjectConst c) {
    String id = c["id"] | "", name = c["name"] | "";
    uint32_t seq = c["seq"] | 0;
    if (!runtime::safeId(id) || !seq || c["boot_id"].as<String>() != journal.boot || c["expires_at"].as<uint32_t>() < time(nullptr) || seq <= journal.lastCommand) return;
    if (!journal.remember(seq, id, "rejected")) { stopRun(Storage, "Command journal unavailable"); return; }
    bool ok = false;
    if (name == "stop") { stopRun(None, "Stopped remotely"); ok = true; }
    else if (name == "load_recipe") {
        // V3.4 has one authoritative source: an atomic full catalog, not patches.
        catalogCheckedAt=0;
        uiMessage="Legacy single-program command rejected. Waiting for full platform sync.";
    } else if (name == "ota" && idleForSettings() && authorization.configured()) {
        outputsOff(); esp_task_wdt_delete(nullptr);
        ok = runtime::ota(network, c["payload"]["release"] | "", "washer", HARDWARE);
        esp_task_wdt_add(nullptr);
        if (ok) { journal.remember(seq, id, "applied"); ESP.restart(); }
    }
    if (!journal.remember(seq, id, ok ? "applied" : "rejected")) stopRun(Storage, "Command journal unavailable");
}
String fetchCatalog(const String& knownDigest) {
    if (WiFi.status()!=WL_CONNECTED || time(nullptr)<1700000000) return "";
    runtime::Https req(network);
    if (!req.begin(network,network.endpoint()+"/programs")) return "";
    const char* headers[]={"X-Catalog-SHA256"}; req.http.collectHeaders(headers,1);
    if (knownDigest.length()==64) req.http.addHeader("If-None-Match","\""+knownDigest+"\"");
    int code=req.http.GET(); catalogHttpStatus=code;
    String hash=req.http.header("X-Catalog-SHA256");
    if (code==304 && knownDigest.length()==64 && hash==knownDigest) return "UNCHANGED";
    if (code!=200 || hash.length()!=64) return "";
    String body=req.body(24576);
    return body.length()?hash+"\n"+body:String();
}
bool applyCatalog(const String& reply) {
    if (reply=="UNCHANGED") return true;
    if (reply.length()<66 || reply[64]!='\n' || !idleForSettings() || display.page==1 || display.page>=6) return false;
    const char* body=reply.c_str()+65;
    uint8_t hash[32]; char hex[65];
    if (mbedtls_sha256_ret(reinterpret_cast<const uint8_t*>(body),reply.length()-65,hash,0)) return false;
    for (unsigned i=0;i<32;++i) snprintf(hex+2*i,3,"%02x",hash[i]);
    if (reply.substring(0,64)!=hex) return false;
    ProgramLibrary candidate;
    {
        DynamicJsonDocument doc(32768);
        if (deserializeJson(doc,body)) return false;
        size_t count=doc["programs"].size();
        // Reject the complete update before allocation if the contiguous RAM is unavailable.
        if (count && ESP.getMaxAllocHeap()<count*sizeof(Recipe)+4096) return false;
        if (!stageCatalog(doc.as<JsonVariantConst>(),network.uid.c_str(),programLibrary,candidate)) return false;
    }
    // The parse buffer is freed before the disk serialization buffer is allocated.
    if (catalogDigest==hex) return true;
    int pending=librarySelection<programLibrary.count?candidate.find(programLibrary.items[librarySelection].id):-1;
    if (!storeLibrary(candidate,hex)) return false;
    librarySelection=display.page==5 && pending>=0?pending:programLibrary.selected;
    if (display.page==5) libraryPage=min(unsigned(libraryPage),programLibrary.count?unsigned((programLibrary.count-1)/3):0u);
    else libraryPage=librarySelection/3;
    display.dirty=true; uiMessage="Program list synchronized from IoT Center.";
    return true;
}
void networkTask(void*) {
    for (;;) {
        String* outgoing = nullptr;
        if (xQueueReceive(requests, &outgoing, portMAX_DELAY) == pdTRUE) {
            String* reply;
            if (outgoing->startsWith("DISCOVER|")) reply = new String(String(runtime::discover(network, deviceId, "washer", HARDWARE)));
            else if (outgoing->startsWith("CATALOG|")) reply = new String(fetchCatalog(outgoing->substring(8)));
            else reply = new String(runtime::exchange(network, *outgoing));
            delete outgoing;
            if (xQueueSend(responses, &reply, pdMS_TO_TICKS(1000)) != pdTRUE) delete reply;
        }
    }
}
void networkTick(uint32_t now) {
    if (!networkReady) return;
    static bool previouslyOnline=false;
    bool online=WiFi.status()==WL_CONNECTED && time(nullptr)>=1700000000;
    if (online && !previouslyOnline) catalogCheckedAt=0;
    previouslyOnline=online;
    if (pendingCatalog.length() && idleForSettings() && display.page!=1 && display.page<6) {
        String deferred=pendingCatalog; pendingCatalog="";
        if (!applyCatalog(deferred)) uiMessage="Sync unavailable. Local programs unchanged.";
    }
    String* text = nullptr;
    if (xQueueReceive(responses, &text, 0) == pdTRUE) {
        if (discoveryInFlight) {
            if (*text == "1") uiMessage = "Instrument registered with IoT Center.";
            else if (*text == "-2") uiMessage = "Device ID security conflict. Contact an IoT manager.";
            discoveryInFlight=false;
        } else if (catalogInFlight) {
            if (display.page==1) pendingCatalog=*text;
            else if (!applyCatalog(*text)) uiMessage="Sync unavailable. Local programs unchanged.";
            catalogInFlight=false;
        } else {
            DynamicJsonDocument reply(8192);
            if (!deserializeJson(reply, *text) && reply["ok"] == true && reply["event_id"].as<String>() == inFlightId) {
                if (inFlightPath.length()) LittleFS.remove(inFlightPath);
                if (reply["command"].is<JsonObject>()) remoteCommand(reply["command"]);
            }
        }
        delete text; inFlight = false; lastPoll = now;
    }
    if (!inFlight && network.bindingRequired && !network.bindingConfirmed && online &&
        (!lastDiscovery || elapsed(now,lastDiscovery)>=10000)) {
        lastDiscovery=now?now:1;
        String* outgoing=new String("DISCOVER|");
        if (xQueueSend(requests,&outgoing,0)==pdTRUE) { inFlight=true; discoveryInFlight=true; }
        else delete outgoing;
        return;
    }
    if (network.bindingRequired && !network.bindingConfirmed) return;
    if (!inFlight && !pendingCatalog.length() && idleForSettings() && display.page!=1 && display.page<6 && (catalogCheckedAt==0 || elapsed(now,catalogCheckedAt)>=30000)) {
        catalogCheckedAt=now?now:1;
        String* outgoing=new String("CATALOG|"+catalogDigest);
        if (xQueueSend(requests,&outgoing,0)==pdTRUE) { inFlight=true; catalogInFlight=true; }
        else delete outgoing;
    }
    if (!inFlight && elapsed(now, lastPoll) >= 5000) {
        lastPoll = now;
        inFlightPath = journal.oldestPath();
        if (!exchangeSchedule.useBacklog(inFlightPath.length() != 0)) inFlightPath = "";
        DynamicJsonDocument doc(3072); String body;
        if (inFlightPath.length()) { body = runtime::readFile(inFlightPath.c_str()); deserializeJson(doc, body); }
        else { snapshot(doc); serializeJson(doc, body); }
        inFlightId = doc["event_id"] | "";
        String* outgoing = new String(body);
        if (xQueueSend(requests, &outgoing, 0) == pdTRUE) inFlight = true;
        else delete outgoing;
    }
}
bool acceptedMotion(int8_t result) {
    if (result == MOVE_OK) return true;
    stopRun(RunTimeout, "Motor command rejected");
    return false;
}
void beginHome() {
    motor->forceStop(); homeComplete=false; homePhase=0;
    motor->setSpeedInHz(WasherMotorProfile::HomeHz);
    motor->setAcceleration(WasherMotorProfile::MotionAcceleration); lastSpeed=0;
}
void homeMotion() {
    if (homePhase == 0 && !motor->isRunning()) {
        if (!acceptedMotion(motor->move(400))) return;
        homePhase = 1;
    } else if (homePhase == 1 && !motor->isRunning()) {
        if (digitalRead(HOME) == LOW) { stopRun(HomeTimeout, "Home switch did not release"); return; }
        if (!acceptedMotion(motor->move(-6400))) return;
        homePhase = 2;
    } else if (homePhase == 2) {
        if (digitalRead(HOME) == LOW) { motor->forceStop(); homePhase = 3; }
        else if (!motor->isRunning()) { stopRun(HomeTimeout, "Home switch not found"); return; }
    } else if (homePhase == 3 && !motor->isRunning()) {
        motor->setCurrentPosition(0);
        if (!acceptedMotion(motor->move(homeOffset))) return;
        homePhase = 4;
    } else if (homePhase == 4 && !motor->isRunning()) { motor->setCurrentPosition(0); homeComplete = rotorHomed = true; }
}
void startupTick(uint32_t now) {
    bool permitted=authorization.allowed() && journal.healthy && screenReady && motionAllowed() && washer.fault==None && motor;
    if (startup.readyToStart(permitted,idleForSettings(),display.page==0,display.acceptsAction(now))) {
        if (startup.start(now,true)) { beginHome(); display.dirty=true; }
    }
    Startup::Phase previous=startup.phase;
    Fault fault=startup.tick(now,permitted,homeComplete,motor && !motor->isRunning());
    if (fault!=None) stopRun(fault,"Initialization failed");
    if (startup.phase!=previous) display.dirty=true;
    if (previous==Startup::Draining && startup.phase==Startup::Ready) {
        outputsOff();
        if (setCleanupRequired(false)) uiMessage="Startup preparation complete. Select a program.";
        else stopRun(Storage,"Initialization state could not be saved");
    }
}
void motionTick() {
    if (startup.active() && motor) {
        digitalWrite(IN_A,LOW); digitalWrite(IN_B,LOW);
        setDrainOutputs(startup.drain(),startup.drain());
        digitalWrite(ENABLE,startup.phase==Startup::Homing?HIGH:LOW);
        if (startup.phase==Startup::Homing) homeMotion();
        return;
    }
    if (!washer.running || !motor) { outputsOff(); return; }
    const Step& step = washer.program.steps[washer.index];
    digitalWrite(ENABLE, HIGH);
    if (step.kind == StepKind::Home) {
        if (homeIndex != washer.index) {
            homeIndex = washer.index; beginHome();
        }
        homeMotion();
    } else if (step.kind == StepKind::FillA || step.kind == StepKind::FillB) {
        homeComplete = false;
        if (fillIndex != washer.index) {
            fillIndex = washer.index; fillPhase = 0; fillMoveAt = millis();
            motor->setSpeedInHz(WasherMotorProfile::PositionHz); motor->setAcceleration(WasherMotorProfile::MotionAcceleration);
            int32_t position=motor->getCurrentPosition()%static_cast<int32_t>(STEPS_PER_REV); if(position<0) position+=STEPS_PER_REV;
            motor->setCurrentPosition(position);
            if (!acceptedMotion(motor->move(cyclicDelta(position,133,STEPS_PER_REV)))) return;
            lastSpeed = 0;
        }
        if (fillPhase == 0 && !motor->isRunning()) { fillPhase = 1; washer.entered = millis(); }
        else if (fillPhase == 1 && elapsed(millis(), washer.entered) >= step.duration) {
            int32_t position=motor->getCurrentPosition()%static_cast<int32_t>(STEPS_PER_REV); if(position<0) position+=STEPS_PER_REV;
            motor->setCurrentPosition(position);
            if (!acceptedMotion(motor->move(cyclicDelta(position,0,STEPS_PER_REV)))) return;
            fillPhase = 2; fillMoveAt = millis();
        } else if (fillPhase == 2 && !motor->isRunning()) fillPhase = 3;
        if ((fillPhase == 0 || fillPhase == 2) && elapsed(millis(), fillMoveAt) > 5000) { stopRun(RunTimeout, "Fill positioning timeout"); return; }
    } else if (step.kind == StepKind::Wait) {
        homeComplete = false;
        if (loadingIndex != washer.index) { loading.reset(); loadingIndex = washer.index; display.dirty = true; }
        if (loading.active) {
            uint32_t now = millis();
            if (loading.expired(now)) { stopRun(RunTimeout, "Loading position timeout"); return; }
            if (elapsed(now, loading.began) >= 25 && !motor->isRunning()) {
                if (!loading.complete(now, true, motor->getCurrentPosition())) { stopRun(RunTimeout, "Loading position incomplete"); return; }
                display.dirty = true;
                String message = "Loading slot reached by step count: " + String(loading.currentSlot() + 1) + "; program remains paused";
                if (!logEvent("waiting", message.c_str())) return;
            }
        } else if (lastSpeed != 0) { motor->stopMove(); lastSpeed = 0; }
        else if (loading.prime(motor->getCurrentPosition(), loadingOffset, !motor->isRunning(), loadingCalibrated && rotorHomed)) display.dirty = true;
    } else {
        homeComplete = false;
        float wanted = washer.outputs.rps;
        if (wanted != lastSpeed) {
            if (wanted == 0) motor->stopMove();
            else {
                motor->setSpeedInHz(static_cast<uint32_t>(fabs(wanted) * STEPS_PER_REV)); motor->setAcceleration(WasherMotorProfile::MotionAcceleration);
                if (!acceptedMotion(wanted > 0 ? motor->runForward() : motor->runBackward())) return;
            }
            lastSpeed = wanted;
        }
    }
    digitalWrite(IN_A, washer.outputs.a ? HIGH : LOW); digitalWrite(IN_B, washer.outputs.b ? HIGH : LOW);
    setDrainOutputs(washer.outputs.drain, washer.outputs.overflow);
}
void paint(uint32_t now) {
    if (!screenReady || display.busy() || (!display.dirty && elapsed(now, lastUi) < 1000)) return;
    lastUi = now;
    tjc::View view;
    view.state = washer.fault != None || !journal.healthy ? "FAULT" : washer.completed ? "COMPLETE" : !authorization.configured() ? "SETUP REQUIRED" : startup.phase == Startup::Pending ? "STARTING" : stateName();
    view.program = washer.program.count ? String(washer.program.label) + " / r" + String(washer.program.revision) : "No program: download from IoT Center";
    const char* steps[] = {"Home rotor", "Fill buffer A", "Fill buffer B", "Wash", "Drain", "Spin dry", "Wait for operator"};
    view.step = washer.running ? "STEP " + String(washer.index+1)+" / "+String(washer.program.count)+"  "+steps[static_cast<unsigned>(washer.program.steps[washer.index].kind)] : String(washer.program.count)+" steps";
    view.temperature = temperature.valid ? String(temperature.value,1)+" C" : "Sensor unavailable";
    uint32_t remaining = washer.running ? (washer.program.steps[washer.index].duration - min(washer.program.steps[washer.index].duration, elapsed(now, washer.entered))) / 1000 : 0;
    view.remaining = washer.waiting ? "Awaiting operator" : washer.running ? "Left " + String(remaining/60)+":"+(remaining%60<10?"0":"")+String(remaining%60) : "";
    view.progress = washer.program.count ? (washer.completed ? 100 : washer.index*100/washer.program.count) : 0;
    view.notice = !authorization.configured() ? "Complete device setup before starting." : !journal.healthy ? "Log storage unavailable. Service required." : washer.fault != None ? "Stopped: check instrument, then reset." : washer.completed ? "Run complete. Confirm rotor is stationary." : !temperature.valid ? "Check temperature sensor." : washer.running ? "Keep hands clear of the rotor." : uiMessage;
    view.detail = WiFi.status()==WL_CONNECTED ? "Device LAN IP: " + WiFi.localIP().toString() + " (DHCP)" : "Wi-Fi offline. Using saved programs.";
    view.deviceId = deviceId;
    view.networkStatus = !networkReady ? "IoT server settings required." :
        network.bindingRequired && !network.bindingConfirmed ? "Add this Device ID in IoT Center." : "IoT Center connected.";
    view.fault = washer.fault!=None || !journal.healthy;
    if (washer.fault == HomeTimeout) view.notice="Homing timed out. Check home sensor and rotor.";
    else if (washer.fault == RunTimeout) view.notice="Motion timed out. Check rotor and motor drive.";
    else if (washer.fault == DoorOpen) view.notice="Interlock open. Check safety input before reset.";
    else if (washer.fault == Storage) view.notice="Run interrupted or storage fault. Check logs, then reset.";
    view.ready = authorization.allowed() && journal.healthy && washer.fault == None && startup.phase==Startup::Ready;
    view.pumpA = pumpDraft.a; view.pumpB = pumpDraft.b;
    if (!washer.running && uiMessage.length() && journal.healthy && washer.fault == None) view.notice = uiMessage;
    if (display.page == 1) {
        Recipe resolved;
        bool pumpReady = programLibrary.count && pumpTiming.resolve(programLibrary.items[programLibrary.selected], resolved);
        if (!view.ready && !view.fault && authorization.configured()) view.notice="Automatic startup preparation is not complete.";
        view.notice = uiMessage.length() ? uiMessage : !view.ready ? view.notice : pumpReady ? "Fill A: " + String(pumpTiming.a) + " s / B: " + String(pumpTiming.b) + " s" : "Set pump times and sync the program first.";
        view.ready = view.ready && pumpReady;
    }
    view.startup = authorization.allowed() && (startup.phase == Startup::Pending || startup.active());
    view.running = washer.running; view.waiting = washer.waiting; view.completed = washer.completed;
    view.programCount=programLibrary.count;
    view.selectedProgram=programLibrary.count ? min<uint8_t>(librarySelection, programLibrary.count-1) : 0;
    if (view.programCount)
        view.programChoice=String(programLibrary.items[view.selectedProgram].label)+" / r"+
            String(programLibrary.items[view.selectedProgram].revision);
    view.wifiSsid=wifiDraft.ssid; view.wifiPassword=wifiDraft.password;
    if (display.page==6 || display.page==10) view.notice=uiMessage;
    view.unsaved = display.page==10 ? pumpDraft.a!=pumpTiming.a || pumpDraft.b!=pumpTiming.b :
        display.page==6 && (network.ssid!=wifiDraft.ssid || network.password!=wifiDraft.password);
    if (view.startup) {
        view.state="INITIALIZING";
        view.step=startup.phase==Startup::Pending?"Starting automatic preparation":
            startup.phase==Startup::Homing?"Homing rotor":"Draining both outlets";
        view.program="Power-on preparation";
        view.notice="Keep hands clear. STOP cancels initialization.";
        view.remaining=startup.phase==Startup::Pending?"Starting now":
            startup.phase==Startup::Draining?String((20000-min(20000u,elapsed(now,startup.entered)))/1000)+" s":"Home timeout: 10 s";
    } else if (authorization.allowed() && display.page==0 && startup.phase==Startup::Stopped) view.notice="Startup preparation stopped.\nPower cycle the washer when it is safe to retry.";
    if (washer.running && washer.program.steps[washer.index].cycles) {
        const Step& step=washer.program.steps[washer.index];
        unsigned cycle=min(unsigned(step.cycles),unsigned(elapsed(now,washer.entered)/(2u*step.reverseSeconds*1000u)+1));
        view.cycle="Cycle "+String(cycle)+" / "+String(step.cycles);
    }
    if (washer.running && !washer.waiting) {
        const StepKind kind=washer.program.steps[washer.index].kind;
        if (washer.finishing) { view.cycle="Stopping rotor"; view.remaining="Wait for stop"; }
        else if (kind==StepKind::FillA || kind==StepKind::FillB) {
            bool positioning=fillIndex!=washer.index || fillPhase==0;
            if (positioning || fillPhase==2) {
                view.cycle=positioning?"Positioning rotor":"Returning rotor"; view.remaining="Please wait";
            }
        }
    }
    view.openRotor = openRotorLayout; view.door = rotorMode == RotorMode::Interlocked && digitalRead(DOOR)==LOW;
    view.slot = loading.currentSlot(); view.targetSlot = loading.nextSlot(); view.loadingDegrees = loading.nextDegrees();
    view.loadingReady = loadingCalibrated && rotorHomed && view.ready;
    view.moving = loading.active || (motor && motor->isRunning());
    if (washer.waiting) {
        if (display.page != 8) display.page = 4;
        view.canCalibrate = authorization.allowed() && rotorHomed && motor && !motor->isRunning() && !loading.active && journal.healthy && washer.fault == None;
        view.notice = !view.loadingReady ? "Confirm slot 1 using SET SLOT 1. No auto-continue." : view.moving ? "Moving. Keep hands clear; wait for stop." : view.slot == BalancedLoading::Unknown ? "ALIGN START moves the rotor to slot 1." : "NEXT rotates to the next slot. Check balance before CONTINUE.";
        if (display.page==8 && uiMessage.length()) view.notice=uiMessage;
    } else if (display.page == 4) display.page = 0;
    display.render(view);
}
void setup() {
    for (uint8_t p : {ENABLE, IN_A, IN_B, DRAIN, OVERFLOW, BUZZER}) { digitalWrite(p, LOW); pinMode(p, OUTPUT); }
    pinMode(HOME, INPUT); pinMode(DOOR, INPUT);
    ledcSetup(0, 5000, 8); ledcSetup(1, 5000, 8); ledcAttachPin(DRAIN, 0); ledcAttachPin(OVERFLOW, 1); outputsOff();
    Serial.begin(115200); Serial2.begin(115200, SERIAL_8N1, 16, 17);
    deviceId = runtime::deviceIdentity("WSH");
    // Arduino-ESP32 defaults to a partition named "spiffs", not our table label.
    storage = LittleFS.begin(false, "/littlefs", 10, "littlefs"); sdReady = SD.begin(SD_CS);
    if (storage) {
        journal.begin();
        DynamicJsonDocument config(1024);
        if (!deserializeJson(config, runtime::readFile("/hardware.json", 1024))) {
            openRotorLayout = config["rotor_mode"].as<String>() == "open";
            bool fieldTest = config["field_test"] == true;
            if (openRotorLayout && (config["open_rotor_commissioned"] == true || (fieldTest && config["open_rotor_test_acknowledged"] == true))) rotorMode = RotorMode::Open;
            else if (config["door_interlock"] == true && config["rotor_mode"].as<String>() != "open") rotorMode = RotorMode::Interlocked;
            commissioned = config["commissioned"] == true && config["profile"].as<String>() == HARDWARE && rotorMode != RotorMode::Unconfigured &&
                (!openRotorLayout || config["open_rotor_commissioned"] == true);
            homeOffset = config["home_offset_steps"] | 0;
            bool validHardware = config["profile"].as<String>() == HARDWARE && rotorMode != RotorMode::Unconfigured &&
                config["home_offset_steps"].is<int32_t>() && homeOffset >= -400 && homeOffset <= 400 && ESP.getFlashChipSize() == 4194304;
            // A field-test authorization is not a claim of physical acceptance.
            authorization.configure(validHardware, commissioned, fieldTest);
            commissioned = authorization.commissioned;
            loadingOffset = config["loading_offset_steps"] | -1;
            // Do not reuse an old one-second jog calibration for full-angle moves.
            loadingHz = config["loading_index_hz"] | 0u;
            loadingCalibrated = config["loading_calibrated"] == true && loadingOffset >= 0 && loadingOffset < static_cast<int32_t>(STEPS_PER_REV) && loadingHz >= WasherMotorProfile::LoadingMinHz && loadingHz <= WasherMotorProfile::LoadingMaxHz;
        }
        loadPumpTiming();
        if (!loadLibrary()) journal.healthy=false;
        String marker = runtime::readFile("/run.json", 512);
        if (marker.length()) {
            DynamicJsonDocument d(512);
            if (!deserializeJson(d, marker)) {
                runId = d["run_id"] | ""; strlcpy(washer.program.id, d["recipe_id"] | "", sizeof(washer.program.id)); washer.program.revision = d["revision"] | 0;
                decodePumpTiming(d["pump_timing"], runPumpTiming);
                if (logEvent("power_loss", "Interrupted run; automatic resume prohibited")) { LittleFS.remove("/run.json"); runId = ""; }
            } else journal.healthy = false;
            washer.fault = Storage;
        }
        networkReady = network.load(true, deviceId);
    } else journal.healthy = false;
    motion.init(); motor = motion.stepperConnectToPin(STEP);
    if (motor) { motor->setDirectionPin(DIRECTION); motor->setAcceleration(WasherMotorProfile::MotionAcceleration); }
    else { commissioned = false; authorization.configure(false, false, false); }
    sensors.begin(); sensors.setResolution(11); sensors.setWaitForConversion(false);
    probeAttached = sensors.getDeviceCount() == 1 && sensors.getAddress(probeAddress, 0);
    if (probeAttached) sensors.setResolution(probeAddress,11);
    requests = xQueueCreate(1, sizeof(String*)); responses = xQueueCreate(1, sizeof(String*));
    // TLS certificate verification can occupy the CPU for seconds. Share priority
    // with IDLE0 so it can still feed its watchdog; keep motion on the other core.
    if (networkReady && requests && responses)
        networkReady = xTaskCreatePinnedToCore(networkTask, "instrument_net", 12288, nullptr, tskIDLE_PRIORITY, &networkTaskHandle, 0) == pdPASS;
    else networkReady = false;
    esp_task_wdt_init(3, true); esp_task_wdt_add(nullptr);
}
void loop() {
    esp_task_wdt_reset(); uint32_t now = millis();
    serialTick();
    now = millis();
    if (screenReady && elapsed(now, screenSeen) > 10000) {
        screenReady = false;
        if (washer.running || startup.active()) stopRun(Storage, "Local screen connection lost");
    }
    if (!conversion) {
        if (!probeAttached && sensors.getAddress(probeAddress,0)) { probeAttached=true; sensors.setResolution(probeAddress,11); }
        sensors.requestTemperatures(); conversionAt = now; conversion = true;
    }
    else if (elapsed(now, conversionAt) >= 400) {
        bool wasValid = temperature.valid;
        temperature.value = probeAttached ? sensors.getTempC(probeAddress) : DEVICE_DISCONNECTED_C; temperature.sampled = now;
        temperature.valid = std::isfinite(temperature.value) && temperature.value != DEVICE_DISCONNECTED_C && temperature.value != 85 && temperature.value >= -20 && temperature.value < 85;
        if (!temperature.valid) probeAttached=false;
        conversion = false;
        if (washer.running && wasValid != temperature.valid) logEvent(temperature.valid ? "sensor_recovered" : "sensor_warning", temperature.valid ? "Liquid temperature reading restored" : "Liquid temperature unavailable; timed program continues");
    }
    bool before = washer.running; uint8_t prior = washer.index; bool waited = washer.waiting;
    // Local Continue may have reset the step clock after this loop began.
    now = millis();
    startupTick(now);
    washer.tick(now, motionAllowed(), homeComplete, fillIndex == washer.index && fillPhase >= 1, fillIndex == washer.index && fillPhase == 3, !motor || !motor->isRunning());
    if (before && !washer.running) {
        outputsOff();
        if (logEvent(washer.completed ? "completed" : "fault", washer.completed ? "Program finished" : "Safety interlock stopped run")) {
            LittleFS.remove("/run.json");
            if (washer.completed && !setCleanupRequired(false)) washer.fault=Storage;
            runId = "";
        }
    } else if (washer.running && prior != washer.index) {
        logEvent("step"); homeComplete = false;
    } else if (washer.waiting && !waited) logEvent("waiting");
    if (!journal.healthy) { startup.stop(); washer.stop(Storage); outputsOff(); }
    motionTick(); networkTick(now); paint(now); display.tick(Serial2, millis());
    usbDiagnostics();
    delay(1);
}
