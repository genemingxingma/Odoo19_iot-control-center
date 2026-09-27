#include "runtime.hpp"
#include "heater_panel.hpp"
#include "heater_runtime.hpp"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Ticker.h>

using namespace instrument;
constexpr const char* HARDWARE = "heater-esp12s-ds18b20-v1";
constexpr const char* CONTROL_INTERFACE = "heater-control-v1";
constexpr uint8_t HEAT = 16, BUZZER = 13, ONE_WIRE = 14, SW1 = 0, SW2 = 2, SW3 = 12;
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
OneWire wire(ONE_WIRE);
DallasTemperature sensors(&wire);
DeviceAddress sensorAddress;
DeviceAddress detectedSensorAddress;
HeaterChannel heater;
Probe probe;
HeaterPanel panel;
runtime::Network network;
runtime::Journal journal;
ExchangeSchedule exchangeSchedule;
Ticker watchdog;
HeaterLoopGuard loopGuard;
volatile bool stalled = false, stopRequested = false, irqHeatEnabled = false;
bool commissioned = false, storage = false, networkReady = false, displayReady = false;
bool settingsReady = false, sensorConfigured = false, converting = false, resampleAfterNetwork = false;
bool detectedSensorAddressValid = false;
uint8_t detectedSensorCount = 0;
HeaterProbeInventory inventory;
bool hardwareReady = false, restoredLoopFault = false, probeScanRequested = true;
bool savedSettings = false;
bool restoredStorageFault = false;
uint32_t lastProbeScan = 0, probeScans = 0, lastConversionAttempt = 0;
uint32_t conversionAt = 0, lastSample = 0, lastPoll = 0, lastPaint = 0, pollDelay = 5000;
uint32_t lastDiscovery = 0;
String recordedFault, deviceId;

void IRAM_ATTR heatKeyInterrupt() {
    if (irqHeatEnabled) { digitalWrite(HEAT, LOW); loopGuard.powered = false; stopRequested = true; }
}
void outputsOff() { digitalWrite(HEAT, LOW); }
void stopHeat() { irqHeatEnabled = false; loopGuard.powered = false; heater.stop(); outputsOff(); }
void applyOutput() {
    noInterrupts();
    irqHeatEnabled = heater.enabled;
    bool on = heater.output && !stopRequested && !stalled && !loopGuard.triggered;
    loopGuard.powered = on;
    digitalWrite(HEAT, on ? HIGH : LOW);
    interrupts();
}
void pauseForMaintenance(HeaterPhase phase) {
    heater.pause(millis());
    noInterrupts();
    outputsOff(); loopGuard.powered = false; loopGuard.phase = phase;
    interrupts();
    // Retain the last timestamped reading for logging; never reuse it to resume heat.
    resampleAfterNetwork = true; converting = false;
}
void scanProbe() {
    pauseForMaintenance(HeaterPhase::Probe);
    inventory = scanHeaterProbe(wire, sensors);
    detectedSensorCount = inventory.count;
    detectedSensorAddressValid = inventory.ready();
    if (detectedSensorAddressValid) memcpy(detectedSensorAddress, inventory.address, 8);
    bool matched = sensorConfigured && inventory.matches(sensorAddress);
    if (heater.enabled && !matched) { heater.fault = Sensor; stopHeat(); }
    commissioned = hardwareReady && matched;
    lastProbeScan = millis(); ++probeScans; probeScanRequested = false;
}
bool parseSettings(JsonVariantConst d, HeaterChannel& h) {
    if (d.containsKey("b") || !d["a"].is<float>() || !d["rise_window_s"].is<uint32_t>() || !d["minimum_rise_c"].is<float>()) return false;
    return h.setTarget(d["a"]) && h.configureProtection(d["rise_window_s"], d["minimum_rise_c"]);
}
bool readAddress(const String& value) {
    if (value.length() != 16) return false;
    for (int i = 0; i < 8; ++i) {
        if (!isxdigit(value[2*i]) || !isxdigit(value[2*i+1])) return false;
        sensorAddress[i] = strtoul(value.substring(2*i, 2*i+2).c_str(), nullptr, 16);
    }
    return sensorAddress[0] == 0x28 && OneWire::crc8(sensorAddress, 7) == sensorAddress[7];
}
String addressText(const DeviceAddress& address) {
    char value[17];
    for (uint8_t i = 0; i < 8; ++i) snprintf(value + i * 2, sizeof(value) - i * 2, "%02X", address[i]);
    return value;
}
const char* faultCode() {
    if (!journal.healthy || restoredStorageFault) return "storage";
    if (stalled) return "loop_stalled";
    switch (heater.fault) {
        case Sensor: return "sensor";
        case NoTemperatureRise: return "no_rise";
        case OverTemperature: return "over_temperature";
        default: return commissioned ? "none" : "configuration";
    }
}
const char* alarmText() {
    if (!journal.healthy || restoredStorageFault) return "STORAGE: HEAT OFF";
    if (stalled) return "LOOP: HEAT OFF";
    if (heater.fault == Sensor) return "SENSOR: HEAT OFF";
    if (heater.fault == NoTemperatureRise) return "NO RISE: HEAT OFF";
    if (heater.fault == OverTemperature) return "HOT: HEAT OFF";
    if (!commissioned) return "SETUP REQUIRED";
    if (!settingsReady) return "WAIT IOT SETPOINT";
    return "";
}
void snapshot(JsonDocument& d, bool observation) {
    journal.envelope(d); d["observation"] = observation;
    JsonObject s = d.createNestedObject("status");
    s["state"] = !commissioned ? "uncommissioned" : strcmp(faultCode(), "none") ? "fault" : heater.enabled ? "heating" : "idle";
    s["firmware"] = runtime::version; s["hardware"] = HARDWARE;
    s["device_id"] = deviceId;
    s["control_interface"] = CONTROL_INTERFACE; s["local_enable"] = true; s["remote_start"] = false;
    s["build"] = "IMYTESTFW1:heater:heater-esp12s-ds18b20-v1:" INSTRUMENT_STRING_VALUE(INSTRUMENT_FIRMWARE_VERSION) ":END";
    char chip[7]; snprintf(chip, sizeof(chip), "%06X", ESP.getChipId()); s["chip_id"] = chip;
    s["ip"] = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String();
    s["enabled"] = heater.enabled; s["settings_ready"] = settingsReady;
    s["setpoint_source"] = savedSettings ? "saved" : "default";
    s["control_method"] = "pi_fixed";
    s["temperature_record_interval_s"] = HeaterObservationMs / 1000;
    s["dropped_observations"] = journal.droppedObservations;
    s["journal_pending"] = journal.pending(); s["journal_free"] = journal.criticalFree();
    s["communication_pause"] = resampleAfterNetwork;
    s["rise_window_s"] = heater.riseWindowMs / 1000; s["minimum_rise_c"] = heater.minimumRise;
    JsonObject p = s.createNestedObject("a");
    p["valid"] = probe.valid && elapsed(millis(), probe.sampled) <= 3000;
    if (p["valid"].as<bool>()) p["temperature"] = probe.value;
    p["target"] = heater.target; p["output"] = digitalRead(HEAT) == HIGH; p["demand"] = heater.demand; p["fault"] = faultCode();
    p["power_percent"] = heater.powerPercent();
}
void recordFault() {
    if (!storage || recordedFault == faultCode()) return;
    pauseForMaintenance(HeaterPhase::FaultStorage);
    DynamicJsonDocument marker(128); marker["fault"] = faultCode();
    String text; serializeJson(marker, text);
    if (!runtime::atomicFile("/heater-fault.json", text)) { journal.healthy = false; stopHeat(); return; }
    recordedFault = faultCode();
    if (recordedFault != "none" && recordedFault != "configuration") {
        DynamicJsonDocument event(1536); snapshot(event, false); event["alarm"] = true;
        if (!journal.save(event)) stopHeat();
    }
}
void loadFault() {
    if (!LittleFS.exists("/heater-fault.json")) return;
    DynamicJsonDocument d(128);
    if (deserializeJson(d, runtime::readFile("/heater-fault.json", 128))) { journal.healthy = false; return; }
    String code = d["fault"] | "";
    if (code == "sensor") heater.fault = Sensor;
    else if (code == "no_rise") heater.fault = NoTemperatureRise;
    else if (code == "over_temperature") heater.fault = OverTemperature;
    else if (code == "loop_stalled") { stalled = true; restoredLoopFault = true; }
    else if (code == "storage") restoredStorageFault = true;
    else if (code != "none" && code != "configuration") journal.healthy = false;
    recordedFault = code;
}
void acknowledgeFault() {
    if (!commissioned || !settingsReady || !journal.healthy || resampleAfterNetwork || heater.condition(probe, millis()) != None) return;
    // Reset remains OFF. A separate, fresh SW2 press is required to enable heat.
    stopHeat();
    pauseForMaintenance(HeaterPhase::FaultStorage);
    if (!runtime::atomicFile("/heater-fault.json", "{\"fault\":\"none\"}")) { journal.healthy = false; return; }
    heater.fault = None; stalled = restoredLoopFault = false;
    restoredStorageFault = false;
    loopGuard.triggered = false; loopGuard.tripGapMs = 0; recordedFault = "none";
}
void handleCommand(JsonObjectConst c) {
    String id = c["id"] | "", name = c["name"] | "";
    uint32_t seq = c["seq"] | 0;
    if (!runtime::safeId(id) || !seq || c["boot_id"].as<String>() != journal.boot || c["expires_at"].as<uint32_t>() <= time(nullptr) || seq <= journal.lastCommand) return;
    if (!journal.remember(seq, id, "rejected")) { stopHeat(); return; }
    bool ok = false;
    if (name == "stop") { stopHeat(); panel.inhibitHeatUntilRelease(); ok = true; }
    else if (name == "set_temperature") {
        HeaterChannel candidate = heater;
        if (parseSettings(c["payload"], candidate)) {
            DynamicJsonDocument target(768); target.set(c["payload"]);
            target["_command"]["seq"]=seq; target["_command"]["id"]=id;
            String text; serializeJson(target, text);
            ok = runtime::atomicFile("/targets.json", text);
            if (ok) { heater = candidate; settingsReady = savedSettings = true; }
            else { journal.healthy = false; stopHeat(); }
        }
    } else if (name == "ota" && !heater.enabled && commissioned && !strcmp(faultCode(), "none")) {
        stopHeat();
        ok = runtime::ota(network, c["payload"]["release"] | "", "heater", HARDWARE);
        if (ok) { journal.remember(seq, id, "applied"); ESP.restart(); }
    }
    if (!journal.remember(seq, id, ok ? "applied" : "rejected")) stopHeat();
}
void paint() {
    if (!displayReady) return;
    char value[12], target[12];
    if (probe.valid && elapsed(millis(), probe.sampled) <= 3000) snprintf(value, sizeof(value), "%.1f", probe.value);
    else strcpy(value, "--.-");
    if (settingsReady) snprintf(target, sizeof(target), "%.2f C", heater.target);
    else strcpy(target, "NOT SET");
    String ip = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "NOT CONNECTED";
    const char* code = faultCode();
    HeaterView v; v.state = !commissioned ? "SETUP" : !settingsReady ? "SET TEMP" : heater.enabled ? "READY" : "OFF";
    v.temperature = value; v.target = target; v.deviceId = deviceId.c_str(); v.ip = ip.c_str(); v.version = runtime::version;
    v.online = WiFi.status() == WL_CONNECTED; v.output = digitalRead(HEAT) == HIGH;
    // Setup can show temperature and identity while the persisted fault stays latched.
    v.fault = (commissioned || !journal.healthy || heater.fault == Sensor || restoredStorageFault) && strcmp(code, "none") && strcmp(code, "configuration");
    v.targetSaved = savedSettings;
    v.alarm = alarmText(); v.page = panel.page;
    drawHeater(oled, v);
}
void attachWatchdog() {
    loopGuard.beat(millis());
    watchdog.attach_ms(100, [] {
        // Snapshot before sampling the clock, never subtract a future heartbeat.
        uint32_t beat = loopGuard.heartbeat;
        if (loopGuard.check(millis(), beat)) outputsOff();
    });
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
        bool requested = !overflow && !strcmp(input, "STATUS");
        bool scan = !overflow && !strcmp(input, "PROBE");
        length = 0; overflow = false;
        if (scan && !heater.enabled) probeScanRequested = true;
        if (!requested || elapsed(millis(), lastReply) < 1000) continue;
        lastReply = millis();
        StaticJsonDocument<1536> d;
        d["firmware"] = runtime::version; d["hardware"] = HARDWARE;
        d["uptime_ms"] = millis();
        d["device_id"] = deviceId;
        d["control_interface"] = CONTROL_INTERFACE; d["local_enable"] = true; d["remote_start"] = false;
        d["commissioned"] = commissioned; d["storage"] = storage; d["journal_healthy"] = journal.healthy;
        d["display_ready"] = displayReady; d["wifi_connected"] = WiFi.status() == WL_CONNECTED;
        d["detected_sensor_count"] = detectedSensorCount;
        if (detectedSensorAddressValid) d["detected_sensor_rom"] = addressText(detectedSensorAddress);
        d["probe_scan_count"] = probeScans;
        d["probe_presence"] = inventory.presence; d["probe_crc_error"] = inventory.crcError;
        d["probe_external_power"] = inventory.externalPower;
        d["probe_scratchpad_valid"] = inventory.scratchpadValid;
        d["probe_matches_binding"] = sensorConfigured && inventory.matches(sensorAddress);
        d["loop_fault_restored"] = restoredLoopFault;
        d["storage_fault_restored"] = restoredStorageFault;
        d["journal_observation_limit"] = journal.observationLimit;
        d["journal_entry_limit"] = journal.maximumEntries;
        d["dropped_observations"] = journal.droppedObservations;
        d["journal_pending"] = journal.knownPending; d["journal_critical_events"] = journal.knownCritical;
        d["loop_fault_this_boot"] = loopGuard.triggered;
        d["loop_max_gap_ms"] = loopGuard.maxGapMs;
        d["loop_trip_gap_ms"] = loopGuard.tripGapMs;
        d["loop_trip_phase"] = static_cast<uint8_t>(loopGuard.tripPhase);
        if (WiFi.status() == WL_CONNECTED) { d["ip"] = WiFi.localIP().toString(); d["rssi"] = WiFi.RSSI(); }
        d["platform_configured"] = networkReady; d["settings_ready"] = settingsReady;
        d["setpoint_source"] = savedSettings ? "saved" : "default";
        d["control_method"] = "pi_fixed"; d["power_percent"] = heater.powerPercent();
        d["temperature_record_interval_s"] = HeaterObservationMs / 1000;
        d["enabled"] = heater.enabled; d["output"] = digitalRead(HEAT) == HIGH; d["fault"] = faultCode();
        d["buzzer"] = digitalRead(BUZZER) == HIGH;
        d["temperature_valid"] = probe.valid && elapsed(millis(), probe.sampled) <= 3000;
        if (d["temperature_valid"].as<bool>()) d["temperature"] = probe.value;
        if (settingsReady) d["target"] = heater.target;
        Serial.print("IOT_STATUS "); serializeJson(d, Serial); Serial.println();
    }
}
void setup() {
    digitalWrite(HEAT, LOW); pinMode(HEAT, OUTPUT); outputsOff();
    digitalWrite(BUZZER, LOW); pinMode(BUZZER, OUTPUT);
    for (uint8_t pin : {SW1, SW2, SW3}) pinMode(pin, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(SW2), heatKeyInterrupt, FALLING);
    Serial.begin(115200);
    heaterDefaults(heater); settingsReady = true;
    deviceId = runtime::deviceIdentity("HTR");
    Wire.begin(4, 5); Wire.setClock(100000); Wire.setClockStretchLimit(1000);
    Wire.beginTransmission(0x3C);
    displayReady = Wire.endTransmission() == 0 && oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
    LittleFS.setConfig(LittleFSConfig(false)); storage = LittleFS.begin();
    if (storage) {
        journal.begin(true);
        DynamicJsonDocument config(1024);
        if (!deserializeJson(config, runtime::readFile("/hardware.json", 1024))) {
            sensorConfigured = readAddress(config["sensor_rom"] | "");
            commissioned = config["commissioned"] == true && config["profile"].as<String>() == HARDWARE &&
                config["output_active_high"] == true && sensorConfigured;
        }
        DynamicJsonDocument d(768);
        if (LittleFS.exists("/targets.json")) {
            settingsReady = !deserializeJson(d, runtime::readFile("/targets.json", 768)) && parseSettings(d.as<JsonVariantConst>(), heater);
            savedSettings = settingsReady;
            if (!settingsReady) journal.healthy = false;
        }
        if (savedSettings && d["_command"]["seq"].is<uint32_t>() && runtime::safeId(d["_command"]["id"].as<String>())) {
            uint32_t seq=d["_command"]["seq"]; String id=d["_command"]["id"];
            if (seq==journal.lastCommand && journal.ackId==id && journal.ackResult=="rejected") journal.remember(seq,id,"applied");
        }
        loadFault(); networkReady = network.load(false, deviceId);
    } else journal.healthy = false;
    hardwareReady = commissioned && displayReady && ESP.getFlashChipRealSize() == 4194304;
    commissioned = false;
    // Reinitialize GPIO after SDK startup, not only in the global constructor.
    wire.begin(ONE_WIRE);
    sensors.setWaitForConversion(false); sensors.setAutoSaveScratchPad(false);
    // Addressed operations do not depend on DallasTemperature's cached inventory.
    // Keep the probe's resolution unchanged and wait its full 12-bit conversion.
    attachWatchdog(); paint();
}
void loop() {
    uint32_t now = millis(); loopGuard.beat(now); loopGuard.phase = HeaterPhase::Usb;
    usbDiagnostics();
    if (loopGuard.triggered) stalled = true;
    if (stopRequested) { stopHeat(); panel.inhibitHeatUntilRelease(); stopRequested = false; }
    if (stalled) stopHeat();
    if (!converting && (probeScanRequested || elapsed(now, lastProbeScan) >= (inventory.ready() ? 60000u : 1000u))) scanProbe();
    now = millis();
    if (now >= 3000 && sensorConfigured && !inventory.matches(sensorAddress)) {
        if (heater.fault == None) heater.fault = Sensor;
        stopHeat();
    }
    loopGuard.phase = HeaterPhase::Probe;
    if (!converting && sensorConfigured && inventory.matches(sensorAddress) && elapsed(millis(), lastConversionAttempt) >= 1000) {
        lastConversionAttempt = millis();
        auto request = sensors.requestTemperaturesByAddress(sensorAddress);
        conversionAt = millis(); converting = request.result;
        if (!request.result) {
            probe.valid = false;
            if (commissioned) { heater.fault = Sensor; stopHeat(); }
        }
    }
    // A probe power cycle restores its 12-bit conversion time, even if setup
    // configured 11 bits. Never read an unfinished conversion after reconnect.
    else if (converting && elapsed(now, conversionAt) >= 750) {
        float t = sensorConfigured ? sensors.getTempC(sensorAddress) : DEVICE_DISCONNECTED_C;
        probe = {t, now, std::isfinite(t) && t != DEVICE_DISCONNECTED_C && t != 85 && t >= -20 && t < 85};
        converting = false; resampleAfterNetwork = false;
        if (commissioned && heater.condition(probe, now) != None) { heater.fault = heater.condition(probe, now); stopHeat(); }
    }
    loopGuard.phase = HeaterPhase::Control;
    uint8_t keys = (digitalRead(SW1) == LOW ? 1 : 0) | (digitalRead(SW2) == LOW ? 2 : 0) | (digitalRead(SW3) == LOW ? 4 : 0);
    auto action = panel.poll(now, keys, heater.enabled, heater.fault != None || stalled);
    if (action == HeaterAction::Stop) stopHeat();
    else if (action == HeaterAction::Acknowledge) acknowledgeFault();
    else if (action == HeaterAction::Enable && commissioned && settingsReady && journal.healthy && !stalled && !resampleAfterNetwork && heater.fault == None) heater.arm(probe, now);
    if (!commissioned || !settingsReady || !journal.healthy || restoredStorageFault || stalled) stopHeat();
    if (resampleAfterNetwork) heater.pause(now); else heater.tick(probe, now);
    applyOutput(); recordFault();
    bool audibleFault = heater.fault != None || !journal.healthy || loopGuard.triggered || (stalled && commissioned);
    digitalWrite(BUZZER, audibleFault && now % 2000 < 200 ? HIGH : LOW);
    loopGuard.phase = HeaterPhase::Display;
    if (elapsed(now, lastPaint) >= 250) { lastPaint = now; paint(); }
    if (storage && elapsed(now, lastSample) >= HeaterObservationMs) {
        pauseForMaintenance(HeaterPhase::Observation);
        lastSample = now; DynamicJsonDocument d(1536); snapshot(d, true); if (!journal.save(d, true)) stopHeat();
    }
    if (networkReady && WiFi.status() == WL_CONNECTED && time(nullptr) >= 1700000000 && elapsed(now, lastPoll) >= pollDelay && !keys && !resampleAfterNetwork) {
        if (network.bindingRequired && !network.bindingConfirmed) {
            if (lastDiscovery && elapsed(now, lastDiscovery) < 10000) { delay(1); return; }
            lastDiscovery = now ? now : 1;
            pauseForMaintenance(HeaterPhase::Network);
            int result = runtime::discover(network, deviceId, "heater", HARDWARE);
            pollDelay = result == 1 ? 5000 : min(pollDelay * 2, 60000u);
            resampleAfterNetwork = true; converting = false;
            delay(1); return;
        }
        lastPoll = now;
        pauseForMaintenance(HeaterPhase::Network);
        String path = journal.oldestPath(), text;
        if (!exchangeSchedule.useBacklog(path.length() != 0)) path = "";
        if (path.length()) text = runtime::readFile(path.c_str());
        else { DynamicJsonDocument d(1536); snapshot(d, false); serializeJson(d, text); }
        // TLS is synchronous: remove power first. The SW2 interrupt latches STOP
        // during the exchange so a short press cannot be lost.
        String response = runtime::exchange(network, text);
        DynamicJsonDocument reply(2048), sent(1536);
        bool accepted = !deserializeJson(reply, response) && !deserializeJson(sent, text) && reply["ok"] == true && reply["event_id"].as<String>() == sent["event_id"].as<String>();
        if (accepted) {
            if (path.length()) LittleFS.remove(path);
            if (reply["command"].is<JsonObject>()) handleCommand(reply["command"]);
        }
        pollDelay = accepted ? 5000 : min(pollDelay * 2, 60000u);
        resampleAfterNetwork = true; converting = false;
    }
    loopGuard.phase = HeaterPhase::Idle;
    delay(1);
}
