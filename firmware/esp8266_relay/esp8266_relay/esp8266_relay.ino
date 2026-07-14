#include <ArduinoJson.h>
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
#include <ESP8266httpUpdate.h>
#include <WiFiClientSecureBearSSL.h>
#include <LittleFS.h>
#include <PubSubClient.h>
#include <time.h>

static const unsigned long WIFI_FAST_BLINK_MS = 120;
static const unsigned long MQTT_SLOW_BLINK_MS = 500;
static const unsigned long OTA_ULTRA_FAST_BLINK_MS = 45;
static const unsigned long CONFIG_REQUIRE_CLIENT_MS = 30000;
static const unsigned long MQTT_PRIMARY_RETRY_MS = 300000;
static const uint8_t MQTT_ENDPOINT_FAILURE_THRESHOLD = 3;
static const uint16_t MQTT_PACKET_BUFFER_BYTES = 1536;

const char* DEFAULT_WIFI_SSID = "iMyTest_IoT";
const char* DEFAULT_WIFI_PASSWORD = "iMyTest_IoT";
const char* DEFAULT_MQTT_HOST = "iot.imytest.com";
const uint16_t DEFAULT_MQTT_PORT = 1883;
const char* DEFAULT_MQTT_USERNAME = "imytest";
const char* DEFAULT_MQTT_PASSWORD = "imytest";
const char* DEFAULT_TOPIC_ROOT = "iot/relay";
const char* DEFAULT_DEVICE_SERIAL = "";
const char* DEFAULT_BOARD_PROFILE = "";
const char* DEFAULT_FIRMWARE_UPGRADE_URL = "iot.imytest.com";
const char* CONFIG_AP_PASSWORD = "iMyTestIoT";

const char* PROFILE_RELAY = "IoT-Relay";
const char* PROFILE_OUTLET = "IoT-Outlet";

const char* FIRMWARE_VERSION = "1.8.10";
const char* FIRMWARE_HARDWARE_PROFILE = "esp8266-1m-dout-64kfs";

const char* NTP_SERVER_1 = "pool.ntp.org";
const char* NTP_SERVER_2 = "time.cloudflare.com";

static const char* STATE_FILE = "/state.json";
static const char* CONFIG_FILE = "/config.json";
static const size_t MAX_SCHEDULE_ENTRIES = 64;

struct ScheduleEntry {
  uint8_t weekday;   // Monday=0 .. Sunday=6
  uint8_t hour;      // 0..23
  uint8_t minute;    // 0..59
  int16_t offsetMin; // Local offset minutes from UTC
  bool turnOn;       // true=on, false=off
};

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
ESP8266WebServer configServer(80);

String topicCommand;
String topicStatus;
String topicTelemetry;
String moduleId;
String apSsid;

String cfgWifiSsid = DEFAULT_WIFI_SSID;
String cfgWifiPassword = DEFAULT_WIFI_PASSWORD;
String cfgMqttHost = DEFAULT_MQTT_HOST;
uint16_t cfgMqttPort = DEFAULT_MQTT_PORT;
String cfgMqttFallbackHost;
uint16_t cfgMqttFallbackPort = DEFAULT_MQTT_PORT;
String cfgMqttUsername = DEFAULT_MQTT_USERNAME;
String cfgMqttPassword = DEFAULT_MQTT_PASSWORD;
String cfgTopicRoot = DEFAULT_TOPIC_ROOT;
String cfgDeviceSerial = DEFAULT_DEVICE_SERIAL;
String cfgBoardProfile = DEFAULT_BOARD_PROFILE;
String cfgFirmwareUpgradeUrl = DEFAULT_FIRMWARE_UPGRADE_URL;

uint8_t relayPin = 4;
uint8_t buttonPin = 12;
uint8_t wifiLedPin = 2;
bool wifiLedActiveLow = true;
bool relayActiveLow = false;

bool relayOn = false;
bool lastButtonLevel = HIGH;
int scheduleVersion = 0;
ScheduleEntry schedules[MAX_SCHEDULE_ENTRIES];
size_t scheduleCount = 0;
long lastExecMinuteKey = -1;
unsigned long lastWifiLedToggleMs = 0;
bool wifiLedBlinkState = false;
unsigned long wifiLedBlinkIntervalMs = WIFI_FAST_BLINK_MS;
bool otaPending = false;
String otaUrlPending;
String otaFallbackUrlPending;
String otaState = "idle";
String otaNote;
bool delayActive = false;
unsigned long delayEndAtMs = 0;
uint32_t delayDurationSec = 0;
uint32_t maxOnSec = 0;
unsigned long relayOnStartedMs = 0;
bool safetyTrip = false;
String lastCommandId;

bool configMode = false;
bool runtimeStarted = false;
bool pinsReady = false;
bool configRestartPending = false;
unsigned long configSavedAtMs = 0;
unsigned long configWindowStartMs = 0;
bool configClientSeen = false;

unsigned long lastWifiConnectAttemptMs = 0;
unsigned long lastMqttConnectAttemptMs = 0;
unsigned long mqttFallbackSelectedAtMs = 0;
uint8_t mqttEndpointFailures = 0;
bool mqttUsingFallback = false;
String activeMqttHost;
uint16_t activeMqttPort = DEFAULT_MQTT_PORT;
void setRelay(bool on, bool persist = true);
void setWifiLed(bool on);
void blinkWifiLed(unsigned long intervalMs);
void updateConnectionLedMode();
void ensureMqtt();
void refreshRuntimeConfig();
void selectMqttEndpoint(bool useFallback);
void startRuntime();
void startConfigPortal();
String normalizeUpgradeUrl(const String& rawUrl);
void detectBoardProfileFromPowerOnButton();
void runSafetyWatchdog();

void applyBoardProfile() {
  String p = cfgBoardProfile;
  if (p.equalsIgnoreCase(PROFILE_OUTLET)) {
    relayPin = 4;
    buttonPin = 5;
    wifiLedPin = 16;
    cfgBoardProfile = PROFILE_OUTLET;
  } else if (p.equalsIgnoreCase(PROFILE_RELAY)) {
    relayPin = 4;
    wifiLedPin = 2;
    buttonPin = 12;
    cfgBoardProfile = PROFILE_RELAY;
  } else {
    cfgBoardProfile = "";
  }
}

void applyPinModes() {
  pinMode(relayPin, OUTPUT);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(wifiLedPin, OUTPUT);
  pinsReady = true;
}

bool isDelayActive() {
  if (!delayActive) {
    return false;
  }
  if ((long)(millis() - delayEndAtMs) >= 0) {
    delayActive = false;
    delayEndAtMs = 0;
    delayDurationSec = 0;
    return false;
  }
  return true;
}

uint32_t delayRemainingSec() {
  if (!isDelayActive()) {
    return 0;
  }
  unsigned long now = millis();
  unsigned long remainingMs = (delayEndAtMs > now) ? (delayEndAtMs - now) : 0;
  return (uint32_t)(remainingMs / 1000UL);
}

void startDelayMode(uint32_t durationSec) {
  if (durationSec == 0) {
    durationSec = 60;
  }
  delayDurationSec = durationSec;
  delayEndAtMs = millis() + durationSec * 1000UL;
  delayActive = true;
  setRelay(true);
}

void cancelDelayMode() {
  delayActive = false;
  delayEndAtMs = 0;
  delayDurationSec = 0;
  setRelay(false);
}

int weekdayMon0FromTmWday(int wday) {
  return (wday + 6) % 7;
}

long minuteKeyFromTm(const tm& t) {
  return (long)t.tm_yday * 1440L + (long)t.tm_hour * 60L + (long)t.tm_min;
}

bool timeSynced() {
  return time(nullptr) > 1700000000;
}

bool saveState() {
  DynamicJsonDocument doc(4096);
  doc["relay_on"] = relayOn;
  doc["schedule_version"] = scheduleVersion;
  doc["max_on_sec"] = maxOnSec;
  doc["last_command_id"] = lastCommandId;

  JsonArray arr = doc.createNestedArray("entries");
  for (size_t i = 0; i < scheduleCount; ++i) {
    JsonObject o = arr.createNestedObject();
    o["weekday"] = schedules[i].weekday;
    o["hour"] = schedules[i].hour;
    o["minute"] = schedules[i].minute;
    o["offset_min"] = schedules[i].offsetMin;
    o["action"] = schedules[i].turnOn ? "on" : "off";
  }

  File f = LittleFS.open(STATE_FILE, "w");
  if (!f) {
    return false;
  }
  serializeJson(doc, f);
  f.close();
  return true;
}

void setRelay(bool on, bool persist) {
  bool changed = relayOn != on;
  if (!pinsReady) {
    relayOn = on;
    return;
  }
  relayOn = on;
  if (on && changed) {
    relayOnStartedMs = millis();
    safetyTrip = false;
  } else if (!on) {
    relayOnStartedMs = 0;
  }
  digitalWrite(relayPin, (on ^ relayActiveLow) ? HIGH : LOW);
  if (persist) {
    saveState();
  }
}

void loadState() {
  if (!LittleFS.exists(STATE_FILE)) {
    setRelay(false, false);
    scheduleVersion = 0;
    scheduleCount = 0;
    saveState();
    return;
  }

  File f = LittleFS.open(STATE_FILE, "r");
  if (!f) {
    return;
  }

  DynamicJsonDocument doc(4096);
  DeserializationError err = deserializeJson(doc, f);
  f.close();
  if (err) {
    return;
  }

  // Always fail safe after boot. Schedules remain stored, but a previous ON
  // state is never restored blindly after a reset or power interruption.
  maxOnSec = doc["max_on_sec"] | 0;
  lastCommandId = String(doc["last_command_id"] | "");
  safetyTrip = false;
  setRelay(false, false);

  scheduleVersion = doc["schedule_version"] | 0;
  scheduleCount = 0;

  JsonArray arr = doc["entries"].as<JsonArray>();
  if (arr.isNull()) {
    return;
  }

  for (JsonVariant v : arr) {
    if (scheduleCount >= MAX_SCHEDULE_ENTRIES) {
      break;
    }
    int weekday = v["weekday"] | -1;
    int hour = v["hour"] | -1;
    int minute = v["minute"] | -1;
    int offsetMin = v["offset_min"] | 0;
    const char* action = v["action"] | "off";

    if (weekday < 0 || weekday > 6 || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
      continue;
    }

    schedules[scheduleCount].weekday = (uint8_t)weekday;
    schedules[scheduleCount].hour = (uint8_t)hour;
    schedules[scheduleCount].minute = (uint8_t)minute;
    schedules[scheduleCount].offsetMin = (int16_t)offsetMin;
    schedules[scheduleCount].turnOn = strcmp(action, "on") == 0;
    scheduleCount += 1;
  }
}

bool saveConfig() {
  DynamicJsonDocument doc(1536);
  doc["wifi_ssid"] = cfgWifiSsid;
  doc["wifi_password"] = cfgWifiPassword;
  doc["mqtt_host"] = cfgMqttHost;
  doc["mqtt_port"] = cfgMqttPort;
  doc["mqtt_fallback_host"] = cfgMqttFallbackHost;
  doc["mqtt_fallback_port"] = cfgMqttFallbackPort;
  doc["mqtt_username"] = cfgMqttUsername;
  doc["mqtt_password"] = cfgMqttPassword;
  doc["topic_root"] = cfgTopicRoot;
  doc["device_serial"] = cfgDeviceSerial;
  doc["board_profile"] = cfgBoardProfile;
  doc["firmware_upgrade_url"] = cfgFirmwareUpgradeUrl;

  File f = LittleFS.open(CONFIG_FILE, "w");
  if (!f) {
    return false;
  }
  serializeJson(doc, f);
  f.close();
  return true;
}

String normalizeUpgradeUrl(const String& rawUrl) {
  String url = rawUrl;
  url.trim();
  if (url.length() == 0) {
    url = String(DEFAULT_FIRMWARE_UPGRADE_URL);
  }
  if (url.length() == 0) {
    return String("");
  }
  if (url.startsWith("http://")) {
    url.remove(0, 7);
    url = String("https://") + url;
  } else if (!url.startsWith("https://")) {
    url = String("https://") + url;
  }
  return url;
}

void loadConfig() {
  cfgWifiSsid = DEFAULT_WIFI_SSID;
  cfgWifiPassword = DEFAULT_WIFI_PASSWORD;
  cfgMqttHost = DEFAULT_MQTT_HOST;
  cfgMqttPort = DEFAULT_MQTT_PORT;
  cfgMqttFallbackHost = "";
  cfgMqttFallbackPort = DEFAULT_MQTT_PORT;
  cfgMqttUsername = DEFAULT_MQTT_USERNAME;
  cfgMqttPassword = DEFAULT_MQTT_PASSWORD;
  cfgTopicRoot = DEFAULT_TOPIC_ROOT;
  cfgDeviceSerial = DEFAULT_DEVICE_SERIAL;
  cfgBoardProfile = DEFAULT_BOARD_PROFILE;
  cfgFirmwareUpgradeUrl = DEFAULT_FIRMWARE_UPGRADE_URL;

  if (!LittleFS.exists(CONFIG_FILE)) {
    saveConfig();
    applyBoardProfile();
    return;
  }

  File f = LittleFS.open(CONFIG_FILE, "r");
  if (!f) {
    applyBoardProfile();
    return;
  }

  DynamicJsonDocument doc(1536);
  DeserializationError err = deserializeJson(doc, f);
  f.close();
  if (err) {
    applyBoardProfile();
    return;
  }

  if (doc.containsKey("wifi_ssid")) {
    cfgWifiSsid = String(doc["wifi_ssid"] | "");
  }
  if (doc.containsKey("wifi_password")) {
    cfgWifiPassword = String(doc["wifi_password"] | "");
  }
  if (doc.containsKey("mqtt_host")) {
    cfgMqttHost = String(doc["mqtt_host"] | "");
  }
  if (doc.containsKey("mqtt_port")) {
    cfgMqttPort = (uint16_t)(doc["mqtt_port"] | 0);
  }
  if (doc.containsKey("mqtt_fallback_host")) {
    cfgMqttFallbackHost = String(doc["mqtt_fallback_host"] | "");
  }
  if (doc.containsKey("mqtt_fallback_port")) {
    cfgMqttFallbackPort = (uint16_t)(doc["mqtt_fallback_port"] | DEFAULT_MQTT_PORT);
  }
  if (doc.containsKey("mqtt_username")) {
    cfgMqttUsername = String(doc["mqtt_username"] | "");
  }
  if (doc.containsKey("mqtt_password")) {
    cfgMqttPassword = String(doc["mqtt_password"] | "");
  }
  if (doc.containsKey("topic_root")) {
    cfgTopicRoot = String(doc["topic_root"] | "");
  }
  if (doc.containsKey("device_serial")) {
    cfgDeviceSerial = String(doc["device_serial"] | "");
  }
  if (doc.containsKey("board_profile")) {
    cfgBoardProfile = String(doc["board_profile"] | "");
  }
  if (doc.containsKey("firmware_upgrade_url")) {
    cfgFirmwareUpgradeUrl = String(doc["firmware_upgrade_url"] | "");
  }

  cfgDeviceSerial.trim();
  bool cfgChanged = false;
  // Force unique identity: always use moduleId as serial/client_id.
  if (!cfgDeviceSerial.equalsIgnoreCase(moduleId)) {
    cfgDeviceSerial = moduleId;
    cfgChanged = true;
  }
  if (cfgChanged) {
    saveConfig();
  }
  applyBoardProfile();
}

void detectBoardProfileFromPowerOnButton() {
  // Let users hold button during power-on to set board profile automatically.
  pinMode(12, INPUT_PULLUP);
  pinMode(5, INPUT_PULLUP);
  delay(40);
  bool relayPressed = (digitalRead(12) == LOW);
  bool outletPressed = (digitalRead(5) == LOW);

  if (relayPressed && !outletPressed) {
    cfgBoardProfile = PROFILE_RELAY;
    applyBoardProfile();
    saveConfig();
  } else if (outletPressed && !relayPressed) {
    cfgBoardProfile = PROFILE_OUTLET;
    applyBoardProfile();
    saveConfig();
  }
}

void publishStatus() {
  bool active = isDelayActive();
  StaticJsonDocument<768> doc;
  doc["state"] = relayOn ? "on" : "off";
  doc["module_id"] = moduleId;
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["hardware_profile"] = FIRMWARE_HARDWARE_PROFILE;
  doc["flash_real_size"] = ESP.getFlashChipRealSize();
  doc["free_heap"] = ESP.getFreeHeap();
  doc["mqtt_host"] = activeMqttHost;
  doc["mqtt_route"] = mqttUsingFallback ? "fallback" : "primary";
  doc["schedule_version"] = scheduleVersion;
  doc["schedule_count"] = (int)scheduleCount;
  doc["ota_state"] = otaState;
  doc["board_profile"] = cfgBoardProfile;
  if (otaNote.length() > 0) {
    doc["ota_note"] = otaNote;
  }
  doc["delay_active"] = active;
  doc["delay_duration_sec"] = delayDurationSec;
  doc["delay_remaining_sec"] = active ? delayRemainingSec() : 0;
  doc["max_on_sec"] = maxOnSec;
  doc["safety_trip"] = safetyTrip;
  if (lastCommandId.length() > 0) {
    doc["last_command_id"] = lastCommandId;
  }

  char out[768];
  size_t len = serializeJson(doc, out);
  mqttClient.publish(topicStatus.c_str(), reinterpret_cast<const uint8_t*>(out), len, true);
}

void otaProgress(int, int) {
  blinkWifiLed(OTA_ULTRA_FAST_BLINK_MS);
}

void applyScheduleSet(JsonDocument& doc) {
  int version = doc["version"] | scheduleVersion;
  JsonArray arr = doc["entries"].as<JsonArray>();
  if (arr.isNull()) {
    return;
  }

  size_t newCount = 0;
  ScheduleEntry tmp[MAX_SCHEDULE_ENTRIES];

  for (JsonVariant v : arr) {
    if (newCount >= MAX_SCHEDULE_ENTRIES) {
      break;
    }

    int weekday = v["weekday"] | -1;
    int hour = v["hour"] | -1;
    int minute = v["minute"] | -1;
    int offsetMin = v["offset_min"] | 0;
    const char* action = v["action"] | "off";

    if (weekday < 0 || weekday > 6 || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
      continue;
    }

    tmp[newCount].weekday = (uint8_t)weekday;
    tmp[newCount].hour = (uint8_t)hour;
    tmp[newCount].minute = (uint8_t)minute;
    tmp[newCount].offsetMin = (int16_t)offsetMin;
    tmp[newCount].turnOn = strcmp(action, "on") == 0;
    newCount += 1;
  }

  for (size_t i = 0; i < newCount; ++i) {
    schedules[i] = tmp[i];
  }
  scheduleCount = newCount;
  scheduleVersion = version;
  lastExecMinuteKey = -1;
  saveState();
  publishStatus();
}

void applyScheduleClear(JsonDocument& doc) {
  int version = doc["version"] | scheduleVersion;
  scheduleCount = 0;
  scheduleVersion = version;
  lastExecMinuteKey = -1;
  saveState();
  publishStatus();
}

void doUpgrade(const char* url, const char* fallbackUrl) {
  String normalizedUrl = normalizeUpgradeUrl(String(url));
  if (!normalizedUrl.startsWith("https://")) {
    otaState = "failed";
    otaNote = "Invalid OTA URL (HTTPS required)";
    publishStatus();
    return;
  }

  otaState = "starting";
  otaNote = "Starting OTA";
  // A firmware transition must never leave the controlled load energized.
  setRelay(false);
  publishStatus();

  mqttClient.disconnect();
  delay(120);

  ESPhttpUpdate.rebootOnUpdate(false);
  ESPhttpUpdate.onProgress(otaProgress);
  BearSSL::WiFiClientSecure secureClient;
  secureClient.setInsecure();
  secureClient.setTimeout(15000);
  t_httpUpdate_return ret = ESPhttpUpdate.update(secureClient, normalizedUrl);
  String fallbackRaw = String(fallbackUrl);
  fallbackRaw.trim();
  String normalizedFallback = fallbackRaw.length() > 0 ? normalizeUpgradeUrl(fallbackRaw) : String("");
  if (
    ret != HTTP_UPDATE_OK
    && normalizedFallback.startsWith("https://")
    && normalizedFallback != normalizedUrl
  ) {
    secureClient.stop();
    otaState = "retrying";
    otaNote = "Primary OTA failed; trying fallback";
    ret = ESPhttpUpdate.update(secureClient, normalizedFallback);
  }
  if (ret == HTTP_UPDATE_OK) {
    otaState = "ok";
    otaNote = "Update complete, rebooting";
    publishStatus();
    delay(250);
    ESP.restart();
    return;
  }

  if (ret == HTTP_UPDATE_NO_UPDATES) {
    otaState = "failed";
    otaNote = "No updates returned by server";
  } else {
    otaState = "failed";
    otaNote = String("OTA failed(") + String(ESPhttpUpdate.getLastError()) + "): " + ESPhttpUpdate.getLastErrorString();
  }

  ensureMqtt();
  publishStatus();
}

void setWifiLed(bool on) {
  if (!pinsReady) {
    return;
  }
  digitalWrite(wifiLedPin, (on ^ wifiLedActiveLow) ? HIGH : LOW);
}

void blinkWifiLed(unsigned long intervalMs) {
  if (wifiLedBlinkIntervalMs != intervalMs) {
    wifiLedBlinkIntervalMs = intervalMs;
    lastWifiLedToggleMs = 0;
    wifiLedBlinkState = false;
  }
  unsigned long now = millis();
  if (now - lastWifiLedToggleMs >= wifiLedBlinkIntervalMs) {
    lastWifiLedToggleMs = now;
    wifiLedBlinkState = !wifiLedBlinkState;
    setWifiLed(wifiLedBlinkState);
  }
}

void updateConnectionLedMode() {
  if (WiFi.status() != WL_CONNECTED) {
    blinkWifiLed(WIFI_FAST_BLINK_MS);
    return;
  }

  if (!mqttClient.connected()) {
    blinkWifiLed(MQTT_SLOW_BLINK_MS);
    return;
  }

  wifiLedBlinkState = true;
  lastWifiLedToggleMs = millis();
  setWifiLed(true);
}

String htmlEscape(const String& s) {
  String out = s;
  out.replace("&", "&amp;");
  out.replace("<", "&lt;");
  out.replace(">", "&gt;");
  out.replace("\"", "&quot;");
  return out;
}

void startConfigPortal() {
  configMode = true;
  runtimeStarted = false;
  configRestartPending = false;
  configWindowStartMs = millis();
  configClientSeen = false;

  mqttClient.disconnect();
  WiFi.disconnect();
  delay(100);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(apSsid.c_str(), CONFIG_AP_PASSWORD);

  configServer.on("/", HTTP_GET, []() {
    configClientSeen = true;
    String page;
    page += "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>";
    page += "<title>iMyTest IoT Module Config</title><style>body{font-family:Arial,sans-serif;max-width:560px;margin:16px auto;padding:0 12px}label{display:block;margin-top:10px;font-weight:600}input,select{width:100%;padding:8px;box-sizing:border-box}button{margin-top:12px;padding:9px 14px}</style></head><body>";
    page += "<h2>iMyTest IoT Module Config</h2>";
    page += "<p>AP SSID: <b>" + htmlEscape(apSsid) + "</b></p>";
    page += "<p>AP Password: <b>" + htmlEscape(String(CONFIG_AP_PASSWORD)) + "</b></p>";
    page += "<p>Firmware Version: <b>" + String(FIRMWARE_VERSION) + "</b></p>";
    page += "<form method='POST' action='/save'>";
    page += "<label>Board Profile</label><select name='board_profile'>";
    page += "<option value=''" + String(cfgBoardProfile.length() == 0 ? " selected" : "") + ">Unselected</option>";
    page += "<option value='IoT-Relay'" + String(cfgBoardProfile == "IoT-Relay" ? " selected" : "") + ">IoT-Relay</option>";
    page += "<option value='IoT-Outlet'" + String(cfgBoardProfile == "IoT-Outlet" ? " selected" : "") + ">IoT-Outlet</option>";
    page += "</select>";
    page += "<label>WiFi SSID</label><input name='wifi_ssid' value='" + htmlEscape(cfgWifiSsid) + "'>";
    page += "<label>WiFi Password</label><input name='wifi_password' value='" + htmlEscape(cfgWifiPassword) + "'>";
    page += "<label>MQTT Host</label><input name='mqtt_host' value='" + htmlEscape(cfgMqttHost) + "'>";
    page += "<label>MQTT Port</label><input name='mqtt_port' value='" + String(cfgMqttPort) + "'>";
    page += "<label>MQTT Fallback Host</label><input name='mqtt_fallback_host' value='" + htmlEscape(cfgMqttFallbackHost) + "'>";
    page += "<label>MQTT Fallback Port</label><input name='mqtt_fallback_port' value='" + String(cfgMqttFallbackPort) + "'>";
    page += "<label>MQTT Username</label><input name='mqtt_username' value='" + htmlEscape(cfgMqttUsername) + "'>";
    page += "<label>MQTT Password</label><input name='mqtt_password' value='" + htmlEscape(cfgMqttPassword) + "'>";
    page += "<label>Device ID (Fixed)</label><input value='" + htmlEscape(moduleId) + "' readonly>";
    page += "<label>Firmware Upgrade URL</label><input name='firmware_upgrade_url' value='" + htmlEscape(cfgFirmwareUpgradeUrl) + "'>";
    page += "<p style='margin-top:6px;font-size:12px;color:#666'>URL format: https://xxx.xx.xx</p>";
    page += "<button type='submit'>Save And Reboot</button></form>";
    page += "<form method='POST' action='/reboot'><button type='submit'>Reboot Now</button></form>";
    page += "<form method='POST' action='/factory_default'><button type='submit'>Factory Default</button></form>";
    page += "</body></html>";
    configServer.send(200, "text/html; charset=utf-8", page);
  });

  configServer.on("/save", HTTP_POST, []() {
    configClientSeen = true;
    String profile = configServer.arg("board_profile");
    String ssid = configServer.arg("wifi_ssid");
    String password = configServer.arg("wifi_password");
    String host = configServer.arg("mqtt_host");
    uint16_t port = (uint16_t)configServer.arg("mqtt_port").toInt();
    String fallbackHost = configServer.arg("mqtt_fallback_host");
    uint16_t fallbackPort = (uint16_t)configServer.arg("mqtt_fallback_port").toInt();
    String username = configServer.arg("mqtt_username");
    String mqttPassword = configServer.arg("mqtt_password");
    String fwUrl = configServer.arg("firmware_upgrade_url");

    if (profile.length() == 0) {
      profile = "";
    } else if (!(profile.equalsIgnoreCase(PROFILE_RELAY) || profile.equalsIgnoreCase(PROFILE_OUTLET))) {
      profile = "";
    }

    cfgBoardProfile = profile;
    cfgWifiSsid = ssid;
    cfgWifiPassword = password;
    cfgMqttHost = host;
    cfgMqttPort = port;
    cfgMqttFallbackHost = fallbackHost;
    cfgMqttFallbackPort = fallbackPort > 0 ? fallbackPort : DEFAULT_MQTT_PORT;
    cfgMqttUsername = username;
    cfgMqttPassword = mqttPassword;
    cfgFirmwareUpgradeUrl = fwUrl;
    applyBoardProfile();
    saveConfig();

    configRestartPending = true;
    configSavedAtMs = millis();
    configServer.send(200, "text/plain; charset=utf-8", "Saved. Device will reboot in 5 seconds.");
  });

  configServer.on("/reboot", HTTP_POST, []() {
    configClientSeen = true;
    configRestartPending = true;
    configSavedAtMs = millis();
    configServer.send(200, "text/plain; charset=utf-8", "Rebooting in 5 seconds.");
  });

  configServer.on("/factory_default", HTTP_POST, []() {
    configClientSeen = true;
    cfgBoardProfile = DEFAULT_BOARD_PROFILE;
    cfgWifiSsid = DEFAULT_WIFI_SSID;
    cfgWifiPassword = DEFAULT_WIFI_PASSWORD;
    cfgMqttHost = DEFAULT_MQTT_HOST;
    cfgMqttPort = DEFAULT_MQTT_PORT;
    cfgMqttFallbackHost = "";
    cfgMqttFallbackPort = DEFAULT_MQTT_PORT;
    cfgMqttUsername = DEFAULT_MQTT_USERNAME;
    cfgMqttPassword = DEFAULT_MQTT_PASSWORD;
    cfgTopicRoot = DEFAULT_TOPIC_ROOT;
    cfgDeviceSerial = moduleId;
    cfgFirmwareUpgradeUrl = DEFAULT_FIRMWARE_UPGRADE_URL;
    applyBoardProfile();
    saveConfig();
    configRestartPending = true;
    configSavedAtMs = millis();
    configServer.send(200, "text/plain; charset=utf-8", "Factory default restored. Rebooting in 5 seconds.");
  });

  configServer.begin();
}

void refreshRuntimeConfig() {
  // Keep runtime identity fixed to moduleId to avoid MQTT client/topic collisions.
  if (!cfgDeviceSerial.equalsIgnoreCase(moduleId)) {
    cfgDeviceSerial = moduleId;
    saveConfig();
  }
  topicCommand = cfgTopicRoot + "/" + cfgDeviceSerial + "/command";
  topicStatus = cfgTopicRoot + "/" + cfgDeviceSerial + "/status";
  topicTelemetry = cfgTopicRoot + "/" + cfgDeviceSerial + "/telemetry";
  selectMqttEndpoint(false);
  mqttClient.setKeepAlive(60);
}

void selectMqttEndpoint(bool useFallback) {
  bool fallbackAvailable = cfgMqttFallbackHost.length() > 0 && !cfgMqttFallbackHost.equalsIgnoreCase(cfgMqttHost);
  mqttUsingFallback = useFallback && fallbackAvailable;
  activeMqttHost = mqttUsingFallback ? cfgMqttFallbackHost : cfgMqttHost;
  activeMqttPort = mqttUsingFallback ? cfgMqttFallbackPort : cfgMqttPort;
  mqttEndpointFailures = 0;
  if (mqttUsingFallback) {
    mqttFallbackSelectedAtMs = millis();
  }
  mqttClient.setServer(activeMqttHost.c_str(), activeMqttPort);
}

void handleCommand(char* topic, byte* payload, unsigned int length) {
  DynamicJsonDocument doc(4096);
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    return;
  }

  const char* command = doc["command"] | "";
  const char* commandId = doc["command_id"] | "";
  bool metadataChanged = false;
  if (strlen(commandId) > 0 && lastCommandId != commandId) {
    lastCommandId = String(commandId);
    metadataChanged = true;
  }
  if (doc.containsKey("max_on_sec")) {
    uint32_t requestedMaxOnSec = (uint32_t)(doc["max_on_sec"] | 0);
    if (maxOnSec != requestedMaxOnSec) {
      maxOnSec = requestedMaxOnSec;
      metadataChanged = true;
    }
  }
  if (metadataChanged) {
    saveState();
  }

  if (strcmp(command, "relay") == 0) {
    if (isDelayActive()) {
      publishStatus();
      return;
    }
    const char* state = doc["state"] | "";
    if (strcmp(state, "on") == 0) {
      setRelay(true);
    } else if (strcmp(state, "off") == 0) {
      setRelay(false);
    } else if (strcmp(state, "toggle") == 0) {
      setRelay(!relayOn);
    }
    publishStatus();
  } else if (strcmp(command, "delay_toggle") == 0) {
    uint32_t durationSec = (uint32_t)(doc["duration_sec"] | 0);
    if (isDelayActive()) {
      cancelDelayMode();
    } else {
      startDelayMode(durationSec);
    }
    publishStatus();
  } else if (strcmp(command, "delay_cancel") == 0) {
    cancelDelayMode();
    publishStatus();
  } else if (strcmp(command, "upgrade") == 0) {
    const char* url = doc["url"] | "";
    if (strlen(url) > 0) {
      otaUrlPending = String(url);
      otaFallbackUrlPending = String(doc["fallback_url"] | "");
      otaState = "queued";
      otaNote = "Upgrade command queued";
      otaPending = true;
      publishStatus();
    }
  } else if (strcmp(command, "network_set") == 0) {
    String primaryHost = String(doc["mqtt_primary_host"] | "");
    uint16_t primaryPort = (uint16_t)(doc["mqtt_primary_port"] | DEFAULT_MQTT_PORT);
    String fallbackHost = String(doc["mqtt_fallback_host"] | "");
    uint16_t fallbackPort = (uint16_t)(doc["mqtt_fallback_port"] | DEFAULT_MQTT_PORT);
    String otaBaseUrl = String(doc["ota_base_url"] | "");
    primaryHost.trim();
    fallbackHost.trim();
    otaBaseUrl.trim();
    if (primaryHost.length() > 0) {
      cfgMqttHost = primaryHost;
      cfgMqttPort = primaryPort > 0 ? primaryPort : DEFAULT_MQTT_PORT;
      cfgMqttFallbackHost = fallbackHost;
      cfgMqttFallbackPort = fallbackPort > 0 ? fallbackPort : DEFAULT_MQTT_PORT;
      if (otaBaseUrl.length() > 0) {
        cfgFirmwareUpgradeUrl = otaBaseUrl;
      }
      saveConfig();
      mqttClient.disconnect();
      selectMqttEndpoint(false);
    }
  } else if (strcmp(command, "schedule_set") == 0) {
    applyScheduleSet(doc);
  } else if (strcmp(command, "schedule_clear") == 0) {
    applyScheduleClear(doc);
  }
}

void ensureWifi() {
  if (!runtimeStarted) {
    return;
  }
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.mode(WIFI_STA);
  unsigned long now = millis();
  if (now - lastWifiConnectAttemptMs > 5000) {
    lastWifiConnectAttemptMs = now;
    WiFi.begin(cfgWifiSsid.c_str(), cfgWifiPassword.c_str());
  }
}

void ensureMqtt() {
  if (!runtimeStarted) {
    return;
  }
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  unsigned long now = millis();
  if (mqttClient.connected()) {
    if (mqttUsingFallback && now - mqttFallbackSelectedAtMs >= MQTT_PRIMARY_RETRY_MS) {
      mqttClient.disconnect();
      selectMqttEndpoint(false);
      lastMqttConnectAttemptMs = 0;
    } else {
      return;
    }
  }
  if (now - lastMqttConnectAttemptMs < 3000) {
    blinkWifiLed(MQTT_SLOW_BLINK_MS);
    return;
  }
  lastMqttConnectAttemptMs = now;

  bool ok;
  if (cfgMqttUsername.length() > 0) {
    ok = mqttClient.connect(cfgDeviceSerial.c_str(), cfgMqttUsername.c_str(), cfgMqttPassword.c_str());
  } else {
    ok = mqttClient.connect(cfgDeviceSerial.c_str());
  }

  if (!ok) {
    mqttEndpointFailures += 1;
    if (mqttEndpointFailures >= MQTT_ENDPOINT_FAILURE_THRESHOLD) {
      selectMqttEndpoint(!mqttUsingFallback);
      lastMqttConnectAttemptMs = 0;
    }
    return;
  }

  mqttEndpointFailures = 0;
  mqttClient.subscribe(topicCommand.c_str(), 1);
  publishStatus();
}

void handleButton() {
  bool level = digitalRead(buttonPin);
  if (lastButtonLevel == HIGH && level == LOW) {
    delay(30);
    if (digitalRead(buttonPin) == LOW) {
      delayActive = false;
      delayEndAtMs = 0;
      delayDurationSec = 0;
      setRelay(!relayOn);
      saveState();
      publishStatus();
    }
  }
  lastButtonLevel = level;
}

void runLocalSchedule() {
  if (isDelayActive()) {
    return;
  }
  if (!timeSynced() || scheduleCount == 0) {
    return;
  }

  time_t nowEpoch = time(nullptr);
  tm nowUtc;
  gmtime_r(&nowEpoch, &nowUtc);
  long globalMinuteKey = minuteKeyFromTm(nowUtc);

  if (globalMinuteKey == lastExecMinuteKey) {
    return;
  }
  lastExecMinuteKey = globalMinuteKey;

  bool touched = false;
  for (size_t i = 0; i < scheduleCount; ++i) {
    time_t localEpoch = nowEpoch + (time_t)schedules[i].offsetMin * 60;
    tm localTm;
    gmtime_r(&localEpoch, &localTm);

    int localWeekday = weekdayMon0FromTmWday(localTm.tm_wday);
    if (localWeekday == schedules[i].weekday && localTm.tm_hour == schedules[i].hour && localTm.tm_min == schedules[i].minute) {
      setRelay(schedules[i].turnOn);
      touched = true;
    }
  }

  if (touched) {
    publishStatus();
  }
}

void runSafetyWatchdog() {
  if (!relayOn || maxOnSec == 0 || relayOnStartedMs == 0) {
    return;
  }
  uint32_t elapsedSec = (uint32_t)((millis() - relayOnStartedMs) / 1000UL);
  if (elapsedSec < maxOnSec) {
    return;
  }
  safetyTrip = true;
  delayActive = false;
  delayEndAtMs = 0;
  delayDurationSec = 0;
  setRelay(false);
  publishStatus();
}

void publishTelemetry() {
  static unsigned long lastMs = 0;
  if (millis() - lastMs < 30000) {
    return;
  }
  lastMs = millis();

  StaticJsonDocument<768> doc;
  doc["rssi"] = WiFi.RSSI();
  doc["uptime_sec"] = millis() / 1000;
  doc["state"] = relayOn ? "on" : "off";
  doc["module_id"] = moduleId;
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["hardware_profile"] = FIRMWARE_HARDWARE_PROFILE;
  doc["flash_real_size"] = ESP.getFlashChipRealSize();
  doc["free_heap"] = ESP.getFreeHeap();
  doc["mqtt_host"] = activeMqttHost;
  doc["mqtt_route"] = mqttUsingFallback ? "fallback" : "primary";
  doc["schedule_version"] = scheduleVersion;
  doc["schedule_count"] = (int)scheduleCount;
  doc["time_synced"] = timeSynced();
  doc["delay_active"] = isDelayActive();
  doc["delay_duration_sec"] = delayDurationSec;
  doc["delay_remaining_sec"] = delayRemainingSec();
  doc["board_profile"] = cfgBoardProfile;
  doc["max_on_sec"] = maxOnSec;
  doc["safety_trip"] = safetyTrip;
  if (lastCommandId.length() > 0) {
    doc["last_command_id"] = lastCommandId;
  }

  char out[768];
  size_t len = serializeJson(doc, out);
  mqttClient.publish(topicTelemetry.c_str(), reinterpret_cast<const uint8_t*>(out), len, false);
}

void startRuntime() {
  if (runtimeStarted) {
    return;
  }
  configMode = false;
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  applyBoardProfile();
  applyPinModes();
  setWifiLed(false);
  setRelay(false, false);
  loadState();
  refreshRuntimeConfig();
  mqttClient.setBufferSize(MQTT_PACKET_BUFFER_BYTES);
  configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);
  runtimeStarted = true;
}

void setup() {
  if (!LittleFS.begin()) {
    LittleFS.format();
    LittleFS.begin();
  }

  char idbuf[9];
  snprintf(idbuf, sizeof(idbuf), "%06X", ESP.getChipId());
  moduleId = String(idbuf);
  apSsid = String("IoT-") + moduleId;

  loadConfig();
  detectBoardProfileFromPowerOnButton();

  mqttClient.setCallback(handleCommand);
  startConfigPortal();
}

void loop() {
  if (configMode) {
    configServer.handleClient();

    if (!configClientSeen && WiFi.softAPgetStationNum() > 0) {
      configClientSeen = true;
    }

    unsigned long elapsed = millis() - configWindowStartMs;
    if (!configClientSeen && elapsed >= CONFIG_REQUIRE_CLIENT_MS && cfgBoardProfile.length() > 0) {
      startRuntime();
    }

    if (configRestartPending && (millis() - configSavedAtMs > 5000)) {
      ESP.restart();
    }

    delay(5);
    return;
  }

  handleButton();
  updateConnectionLedMode();
  ensureWifi();
  ensureMqtt();
  updateConnectionLedMode();

  mqttClient.loop();
  if (otaPending) {
    otaPending = false;
    doUpgrade(otaUrlPending.c_str(), otaFallbackUrlPending.c_str());
  }
  if (delayActive && !isDelayActive()) {
    setRelay(false);
    publishStatus();
  }
  runSafetyWatchdog();
  runLocalSchedule();
  publishTelemetry();

  delay(5);
}
