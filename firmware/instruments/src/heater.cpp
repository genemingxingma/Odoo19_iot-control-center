#include "runtime.hpp"
#include "heater_panel.hpp"
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
volatile uint32_t safetyTick = 0;
volatile bool stalled = false, stopRequested = false, irqHeatEnabled = false;
bool commissioned = false, storage = false, networkReady = false, displayReady = false;
bool settingsReady = false, sensorConfigured = false, converting = false, resampleAfterNetwork = false;
bool detectedSensorAddressValid = false;
uint8_t detectedSensorCount = 0;
uint32_t conversionAt = 0, lastSample = 0, lastPoll = 0, lastPaint = 0, pollDelay = 5000;
uint32_t lastDiscovery = 0;
String recordedFault, deviceId;

void IRAM_ATTR heatKeyInterrupt() {
    if (irqHeatEnabled) { digitalWrite(HEAT, LOW); stopRequested = true; }
}
void outputsOff() { digitalWrite(HEAT, LOW); }
void stopHeat() { irqHeatEnabled = false; heater.stop(); outputsOff(); }
void applyOutput() {
    noInterrupts();
    irqHeatEnabled = heater.enabled;
    digitalWrite(HEAT, heater.output && !stopRequested && !stalled ? HIGH : LOW);
    interrupts();
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
    if (!journal.healthy) return "storage";
    if (stalled) return "loop_stalled";
    if (!commissioned) return "configuration";
    switch (heater.fault) {
        case Sensor: return "sensor";
        case NoTemperatureRise: return "no_rise";
        case OverTemperature: return "over_temperature";
        default: return "none";
    }
}
const char* alarmText() {
    if (!journal.healthy) return "STORAGE: HEAT OFF";
    if (stalled) return "LOOP: HEAT OFF";
    if (!commissioned) return "SETUP REQUIRED";
    if (heater.fault == Sensor) return "SENSOR: HEAT OFF";
    if (heater.fault == NoTemperatureRise) return "NO RISE: HEAT OFF";
    if (heater.fault == OverTemperature) return "HOT: HEAT OFF";
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
    s["dropped_observations"] = journal.droppedObservations;
    s["journal_pending"] = journal.pending(); s["journal_free"] = journal.criticalFree();
    s["communication_pause"] = resampleAfterNetwork;
    s["rise_window_s"] = heater.riseWindowMs / 1000; s["minimum_rise_c"] = heater.minimumRise;
    JsonObject p = s.createNestedObject("a");
    p["valid"] = probe.valid && elapsed(millis(), probe.sampled) <= 3000;
    if (p["valid"].as<bool>()) p["temperature"] = probe.value;
    p["target"] = heater.target; p["output"] = digitalRead(HEAT) == HIGH; p["demand"] = heater.demand; p["fault"] = faultCode();
}
void recordFault() {
    if (!storage || recordedFault == faultCode()) return;
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
    else if (code == "loop_stalled") stalled = true;
    else if (code != "none" && code != "configuration") journal.healthy = false;
    recordedFault = code;
}
void acknowledgeFault() {
    if (!commissioned || !settingsReady || !journal.healthy || resampleAfterNetwork || heater.condition(probe, millis()) != None) return;
    // Reset remains OFF. A separate, fresh SW2 press is required to enable heat.
    stopHeat();
    if (!runtime::atomicFile("/heater-fault.json", "{\"fault\":\"none\"}")) { journal.healthy = false; return; }
    heater.fault = None; stalled = false; recordedFault = "none";
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
            if (ok) { heater = candidate; settingsReady = true; }
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
    v.fault = (commissioned || !journal.healthy) && strcmp(code, "none") && strcmp(code, "configuration");
    v.alarm = alarmText(); v.page = panel.page;
    drawHeater(oled, v);
}
void attachWatchdog() {
    safetyTick = millis();
    watchdog.attach_ms(100, [] { if (millis() - safetyTick > 1000) { outputsOff(); stalled = true; } });
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
        length = 0; overflow = false;
        if (!requested || elapsed(millis(), lastReply) < 1000) continue;
        lastReply = millis();
        StaticJsonDocument<1024> d;
        d["firmware"] = runtime::version; d["hardware"] = HARDWARE;
        d["device_id"] = deviceId;
        d["control_interface"] = CONTROL_INTERFACE; d["local_enable"] = true; d["remote_start"] = false;
        d["commissioned"] = commissioned; d["storage"] = storage; d["journal_healthy"] = journal.healthy;
        d["display_ready"] = displayReady; d["wifi_connected"] = WiFi.status() == WL_CONNECTED;
        d["detected_sensor_count"] = detectedSensorCount;
        if (detectedSensorAddressValid) d["detected_sensor_rom"] = addressText(detectedSensorAddress);
        if (WiFi.status() == WL_CONNECTED) { d["ip"] = WiFi.localIP().toString(); d["rssi"] = WiFi.RSSI(); }
        d["platform_configured"] = networkReady; d["settings_ready"] = settingsReady;
        d["enabled"] = heater.enabled; d["output"] = digitalRead(HEAT) == HIGH; d["fault"] = faultCode();
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
    deviceId = runtime::deviceIdentity("HTR");
    Wire.begin(4, 5); Wire.setClock(100000); Wire.setClockStretchLimit(1000);
    Wire.beginTransmission(0x3C);
    displayReady = Wire.endTransmission() == 0 && oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
    LittleFS.setConfig(LittleFSConfig(false)); storage = LittleFS.begin();
    if (storage) {
        journal.begin();
        DynamicJsonDocument config(1024);
        if (!deserializeJson(config, runtime::readFile("/hardware.json", 1024))) {
            sensorConfigured = readAddress(config["sensor_rom"] | "");
            commissioned = config["commissioned"] == true && config["profile"].as<String>() == HARDWARE &&
                config["output_active_high"] == true && sensorConfigured;
        }
        DynamicJsonDocument d(768);
        settingsReady = !deserializeJson(d, runtime::readFile("/targets.json", 768)) && parseSettings(d.as<JsonVariantConst>(), heater);
        if (settingsReady && d["_command"]["seq"].is<uint32_t>() && runtime::safeId(d["_command"]["id"].as<String>())) {
            uint32_t seq=d["_command"]["seq"]; String id=d["_command"]["id"];
            if (seq==journal.lastCommand && journal.ackId==id && journal.ackResult=="rejected") journal.remember(seq,id,"applied");
        }
        loadFault(); networkReady = network.load(false, deviceId);
    } else journal.healthy = false;
    commissioned = commissioned && displayReady && ESP.getFlashChipRealSize() == 4194304;
    sensors.begin(); sensors.setResolution(11); sensors.setWaitForConversion(false);
    detectedSensorCount = sensors.getDeviceCount();
    detectedSensorAddressValid = detectedSensorCount == 1 && sensors.getAddress(detectedSensorAddress, 0) &&
        detectedSensorAddress[0] == 0x28 && OneWire::crc8(detectedSensorAddress, 7) == detectedSensorAddress[7];
    // This build requires powered, three-wire probes; no strong pull-up driver.
    if (sensors.isParasitePowerMode()) commissioned = false;
    attachWatchdog(); paint();
}
void loop() {
    uint32_t now = millis(); safetyTick = now;
    usbDiagnostics();
    if (stopRequested) { stopHeat(); panel.inhibitHeatUntilRelease(); stopRequested = false; }
    if (stalled) stopHeat();
    if (!converting) { sensors.requestTemperatures(); conversionAt = now; converting = true; }
    // A probe power cycle restores its 12-bit conversion time, even if setup
    // configured 11 bits. Never read an unfinished conversion after reconnect.
    else if (elapsed(now, conversionAt) >= 750) {
        float t = sensorConfigured ? sensors.getTempC(sensorAddress) : DEVICE_DISCONNECTED_C;
        probe = {t, now, std::isfinite(t) && t != DEVICE_DISCONNECTED_C && t != 85 && t >= -20 && t < 85};
        converting = false; resampleAfterNetwork = false;
        if (commissioned && heater.condition(probe, now) != None) { heater.fault = heater.condition(probe, now); stopHeat(); }
    }
    uint8_t keys = (digitalRead(SW1) == LOW ? 1 : 0) | (digitalRead(SW2) == LOW ? 2 : 0) | (digitalRead(SW3) == LOW ? 4 : 0);
    auto action = panel.poll(now, keys, heater.enabled, heater.fault != None || stalled);
    if (action == HeaterAction::Stop) stopHeat();
    else if (action == HeaterAction::Acknowledge) acknowledgeFault();
    else if (action == HeaterAction::Enable && commissioned && settingsReady && journal.healthy && !stalled && !resampleAfterNetwork && heater.fault == None) heater.arm(probe, now);
    if (!commissioned || !settingsReady || !journal.healthy || stalled) stopHeat();
    if (resampleAfterNetwork) heater.pause(now); else heater.tick(probe, now);
    applyOutput(); recordFault();
    digitalWrite(BUZZER, strcmp(faultCode(), "none") && commissioned && now % 2000 < 200 ? HIGH : LOW);
    if (elapsed(now, lastPaint) >= 250) { lastPaint = now; paint(); }
    if (storage && elapsed(now, lastSample) >= 60000) {
        lastSample = now; DynamicJsonDocument d(1536); snapshot(d, true); if (!journal.save(d, true)) stopHeat();
    }
    if (networkReady && WiFi.status() == WL_CONNECTED && time(nullptr) >= 1700000000 && elapsed(now, lastPoll) >= pollDelay && !keys && !resampleAfterNetwork) {
        if (network.bindingRequired && !network.bindingConfirmed) {
            if (lastDiscovery && elapsed(now, lastDiscovery) < 10000) { delay(1); return; }
            lastDiscovery = now ? now : 1;
            heater.pause(now); outputsOff(); watchdog.detach();
            int result = runtime::discover(network, deviceId, "heater", HARDWARE);
            pollDelay = result == 1 ? 5000 : min(pollDelay * 2, 60000u);
            resampleAfterNetwork = true; converting = false; attachWatchdog();
            delay(1); return;
        }
        lastPoll = now;
        String path = journal.oldestPath(), text;
        if (!exchangeSchedule.useBacklog(path.length() != 0)) path = "";
        if (path.length()) text = runtime::readFile(path.c_str());
        else { DynamicJsonDocument d(1536); snapshot(d, false); serializeJson(d, text); }
        // TLS is synchronous: remove power first. The SW2 interrupt latches STOP
        // during the exchange so a short press cannot be lost.
        heater.pause(now); outputsOff(); watchdog.detach();
        String response = runtime::exchange(network, text);
        DynamicJsonDocument reply(2048), sent(1536);
        bool accepted = !deserializeJson(reply, response) && !deserializeJson(sent, text) && reply["ok"] == true && reply["event_id"].as<String>() == sent["event_id"].as<String>();
        if (accepted) {
            if (path.length()) LittleFS.remove(path);
            if (reply["command"].is<JsonObject>()) handleCommand(reply["command"]);
        }
        pollDelay = accepted ? 5000 : min(pollDelay * 2, 60000u);
        resampleAfterNetwork = true; converting = false; attachWatchdog();
    }
    delay(1);
}
