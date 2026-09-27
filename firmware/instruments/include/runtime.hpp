#pragma once
#include "program_catalog.hpp"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <time.h>
#ifdef ESP8266
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <Updater.h>
#else
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Update.h>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>
#include <mbedtls/base64.h>
#endif
#include "control.hpp"
#include "journal_budget.hpp"

namespace runtime {
#define INSTRUMENT_STRING_VALUE_(value) #value
#define INSTRUMENT_STRING_VALUE(value) INSTRUMENT_STRING_VALUE_(value)
#ifndef INSTRUMENT_VERSION
#define INSTRUMENT_VERSION "3.0.3-dev"
#endif
constexpr const char* version = INSTRUMENT_VERSION;
inline String readFile(const char* path, size_t maximum = 8192) {
    File f = LittleFS.open(path, "r");
    if (!f || f.size() > maximum) return "";
    return f.readString();
}
inline bool atomicFile(const char* path, const String& value) {
    String tmp = String(path) + ".tmp";
    File f = LittleFS.open(tmp, "w");
    if (!f) return false;
    size_t n = f.print(value); f.flush(); f.close();
    if (n != value.length()) { LittleFS.remove(tmp); return false; }
    return LittleFS.rename(tmp, path);
}
inline String randomId() {
    char out[33];
    for (int i = 0; i < 4; ++i) {
#ifdef ESP8266
        uint32_t value = os_random();
#else
        uint32_t value = esp_random();
#endif
        snprintf(out + i * 8, 9, "%08lx", (unsigned long)value);
    }
    return out;
}
inline String deviceIdentity(const char* prefix) {
    uint8_t mac[6] = {};
#ifndef ESP8266
    WiFi.mode(WIFI_STA);
#endif
    // ESP8266's MAC accessor reads the SDK identity without starting the radio.
    WiFi.macAddress(mac);
    char value[21];
    snprintf(value, sizeof(value), "%s-%02X%02X%02X%02X%02X%02X", prefix,
        mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return value;
}
inline bool safeId(const String& value) {
    if (!value.length() || value.length() > 64) return false;
    for (char c : value) if (!isalnum(static_cast<unsigned char>(c)) && c != '_' && c != '-') return false;
    return true;
}
struct Network {
    String url, uid, token, ca, ssid, password;
    bool bindingRequired = false, bindingConfirmed = false;
    bool load(bool allowWifiOnly = false, const String& expectedDeviceId = String()) {
        DynamicJsonDocument doc(4096);
        if (deserializeJson(doc, readFile("/network.json", 4096)) && !allowWifiOnly) return false;
        url = doc["url"] | ""; uid = doc["uid"] | ""; token = doc["token"] | "";
        ssid = doc["ssid"] | ""; password = doc["password"] | "";
        bindingRequired = doc["binding_required"] == true;
        bindingConfirmed = !bindingRequired;
        if (bindingRequired && expectedDeviceId.length() && uid != expectedDeviceId) return false;
        if (bindingRequired && LittleFS.exists("/binding.json")) {
            DynamicJsonDocument binding(128);
            bindingConfirmed = !deserializeJson(binding, readFile("/binding.json", 128)) &&
                binding["device_id"].as<String>() == expectedDeviceId;
        }
        if (allowWifiOnly && LittleFS.exists("/wifi.json")) {
            DynamicJsonDocument wifi(512);
            if (deserializeJson(wifi, readFile("/wifi.json", 512))) return false;
            ssid = wifi["ssid"] | ""; password = wifi["password"] | "";
        }
        ca = readFile("/server-ca.pem", 8192);
        while (url.endsWith("/")) url.remove(url.length()-1);
        bool serverReady = url.startsWith("https://") && url.indexOf('@') < 0 && url.indexOf('?') < 0 && url.indexOf('#') < 0 && safeId(uid) && token.length() >= 32 && token.length() <= 128 && ca.length() >= 100;
        if (!allowWifiOnly && (!serverReady || ssid.isEmpty())) return false;
        if (ssid.length() && ssid.length() <= 32 && password.length() <= 64) {
            WiFi.persistent(false); WiFi.mode(WIFI_STA); WiFi.begin(ssid.c_str(), password.c_str());
        }
        // UTC is used on wire; country and display timezone stay in the company.
        configTime(0, 0, doc["ntp"] | "pool.ntp.org");
        return serverReady;
    }
    String endpoint() const { return url + "/iot_control_center/instrument/" + uid; }
    bool confirmBinding(const String& deviceId) {
        if (!bindingRequired) { bindingConfirmed = true; return true; }
        if (deviceId != uid || !atomicFile("/binding.json", "{\"device_id\":\"" + deviceId + "\"}")) return false;
        bindingConfirmed = true; return true;
    }
};
#ifdef ESP8266
using SecureClient = BearSSL::WiFiClientSecure;
#else
using SecureClient = WiFiClientSecure;
#endif
class Https {
public:
    SecureClient client;
    HTTPClient http;
#ifdef ESP8266
    BearSSL::X509List trust;
#endif
    explicit Https(const Network& config)
#ifdef ESP8266
        : trust(config.ca.c_str())
#endif
    {
#ifdef ESP8266
        client.setTrustAnchors(&trust);
#else
        client.setCACert(config.ca.c_str());
#endif
        client.setTimeout(3000);
#ifndef ESP8266
        client.setHandshakeTimeout(12);
#endif
        http.setTimeout(3000);
        http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    }
    ~Https() { http.end(); }
    bool begin(const Network& config, const String& url) {
        if (!url.startsWith(config.url + "/") || !http.begin(client, url)) return false;
        http.addHeader("X-Instrument-Token", config.token);
        return true;
    }
    String body(size_t limit) {
        if (http.getSize() < 0 || static_cast<size_t>(http.getSize()) > limit) return "";
        String result = http.getString();
        return result.length() <= limit ? result : String();
    }
};
inline int discover(Network& net, const String& deviceId, const char* kind, const char* hardware) {
    if (WiFi.status() != WL_CONNECTED || time(nullptr) < 1700000000 || !safeId(deviceId)) return -1;
    Https req(net);
    if (!req.begin(net, net.url + "/iot_control_center/instrument/discover")) return -1;
    StaticJsonDocument<384> request;
    request["schema"] = 1; request["device_id"] = deviceId; request["kind"] = kind;
    request["hardware"] = hardware; request["firmware"] = version;
    String body; serializeJson(request, body);
    req.http.addHeader("Content-Type", "application/json");
    int code = req.http.POST(body);
    if (code != 200) return code == 409 ? -2 : -1;
    DynamicJsonDocument response(384);
    if (deserializeJson(response, req.body(384)) || response["ok"] != true) return -1;
    if (response["bound"] != true) return 0;
    if (response["device_id"].as<String>() != deviceId || !net.confirmBinding(deviceId)) return -1;
    return 1;
}
inline String exchange(const Network& net, const String& body) {
    if (!net.bindingConfirmed || WiFi.status() != WL_CONNECTED || time(nullptr) < 1700000000) return "";
    Https req(net);
    if (!req.begin(net, net.endpoint() + "/exchange")) return "";
    req.http.addHeader("Content-Type", "application/json");
    if (req.http.POST(body) != 200) return "";
    return req.body(8192);
}

class Journal {
public:
    static constexpr unsigned ObservationLimit = 128;
    static constexpr unsigned MaximumEntries = 192;
    unsigned observationLimit = ObservationLimit, maximumEntries = MaximumEntries;
    bool recoverLegacyFull = false;
    unsigned knownPending = 0, knownCritical = 0;
    String boot = randomId(), ackId, ackResult;
    uint32_t sequence = 0, lastCommand = 0;
    uint32_t queueNumber = 0;
    uint32_t droppedObservations = 0;
    bool healthy = true;
private:
    void inventory(unsigned& count, String& oldestObservation) {
        count = 0; oldestObservation = ""; knownCritical = 0;
        auto seen = [&](String name) {
            if (!name.endsWith(".json")) return;
            ++count;
            name = name.substring(name.lastIndexOf('/') + 1);
            if (!name.endsWith(".obs.json")) ++knownCritical;
            if (name.endsWith(".obs.json") && (!oldestObservation.length() || name < oldestObservation)) oldestObservation = name;
            uint32_t number = strtoul(name.c_str(), nullptr, 10);
            if (number > queueNumber) queueNumber = number;
        };
#ifdef ESP8266
        Dir dir = LittleFS.openDir("/events"); while (dir.next()) seen(dir.fileName());
#else
        File dir = LittleFS.open("/events"); File entry = dir.openNextFile();
        while (entry) { seen(entry.path()); entry.close(); entry = dir.openNextFile(); }
#endif
        knownPending = count;
    }
    bool dropObservation(const String& oldestObservation) {
        uint32_t next = droppedObservations >= INT32_MAX ? INT32_MAX : droppedObservations + 1;
        if (recoverLegacyFull && oldestObservation.length()) {
            DynamicJsonDocument sample(4096);
            if (deserializeJson(sample, readFile(("/events/" + oldestObservation).c_str(), 4096)) ||
                sample["observation"] != true || sample["alarm"] == true || sample.containsKey("log")) {
                healthy = false; return false;
            }
        }
        bool ok = instrument::evictObservation(next, oldestObservation.length() != 0, recoverLegacyFull,
            [](uint32_t count) { return atomicFile("/observation-loss.json", "{\"count\":" + String(count) + "}"); },
            [&]() { return LittleFS.remove("/events/" + oldestObservation); });
        if (!ok) { healthy = false; return false; }
        droppedObservations = next;
        return true;
    }
public:
    void begin(bool smallFlash = false) {
        LittleFS.mkdir("/events");
#ifdef ESP8266
        if (smallFlash) {
            FSInfo info;
            if (!LittleFS.info(info) || !info.blockSize) { healthy = false; return; }
            auto budget = instrument::JournalBudget::forBlocks(info.totalBytes / info.blockSize);
            if (budget.observations < 8) { healthy = false; return; }
            observationLimit = budget.observations; maximumEntries = budget.maximum;
            recoverLegacyFull = true;
        }
#else
        (void)smallFlash;
#endif
        DynamicJsonDocument d(512);
        if (LittleFS.exists("/observation-loss.json")) {
            if (deserializeJson(d, readFile("/observation-loss.json", 128)) || !d["count"].is<uint32_t>()) {
                healthy = false; return;
            }
            droppedObservations = d["count"];
            d.clear();
        }
        String text = readFile("/command.json", 512);
        if (text.length()) {
            if (deserializeJson(d, text)) { healthy = false; return; }
            lastCommand = d["seq"] | 0; ackId = d["id"] | ""; ackResult = d["result"] | "rejected";
            if (!lastCommand || !safeId(ackId) || (ackResult != "applied" && ackResult != "rejected")) healthy = false;
        } else if (LittleFS.exists("/command.json")) {
            healthy = false;
        }
        if (healthy && recoverLegacyFull) {
            unsigned count; String oldest;
            inventory(count, oldest);
            while (count > observationLimit && oldest.length()) {
                if (!dropObservation(oldest)) return;
                inventory(count, oldest); delay(1);
            }
            if (count >= maximumEntries) healthy = false;
        }
    }
    bool remember(uint32_t seq, const String& id, const char* result) {
        DynamicJsonDocument d(512); d["seq"] = seq; d["id"] = id; d["result"] = result;
        String text; serializeJson(d, text);
        if (!atomicFile("/command.json", text)) { healthy = false; return false; }
        lastCommand = seq; ackId = id; ackResult = result; return true;
    }
    void envelope(JsonDocument& d) {
        d["protocol"] = 1; d["boot_id"] = boot; d["seq"] = ++sequence;
        d["event_id"] = boot + "-" + String(sequence); d["uptime_ms"] = millis();
        d["sampled_at"] = time(nullptr) >= 1700000000 ? static_cast<uint32_t>(time(nullptr)) : 0;
        if (ackId.length()) { d["ack"]["id"] = ackId; d["ack"]["result"] = ackResult; }
    }
    unsigned pending() {
        unsigned count; String oldest; inventory(count, oldest); return count;
    }
    unsigned criticalFree() {
        unsigned count; String oldest; inventory(count, oldest);
        return count < maximumEntries ? maximumEntries - count : 0;
    }
    bool reserveCritical(unsigned needed) {
        if (!needed || needed >= maximumEntries) return false;
        unsigned count; String oldest;
        inventory(count, oldest);
        while (count + needed > maximumEntries - 1) {
            if (!oldest.length() || !dropObservation(oldest)) return false;
            inventory(count, oldest);
        }
        return true;
    }
    bool save(JsonDocument& doc, bool rollingObservation = false, bool terminal = false) {
        unsigned count; String oldestObservation; inventory(count, oldestObservation);
        if (rollingObservation && (doc["observation"] != true || doc["alarm"] == true)) { healthy = false; return false; }
        if (rollingObservation && count >= observationLimit) {
            // Ordinary samples are a bounded offline ring; alarms and command
            // receipts are never evicted. Persist a conservative loss counter.
            if (!dropObservation(oldestObservation)) return false;
            if (!oldestObservation.length()) return true;
            --count;
        }
        unsigned limit = terminal ? maximumEntries : maximumEntries - 1;
        if (count >= limit || queueNumber == UINT32_MAX) { healthy = false; return false; }
        if (rollingObservation) doc["status"]["dropped_observations"] = droppedObservations;
        String text; serializeJson(doc, text);
        char path[40]; snprintf(path, sizeof(path), rollingObservation ? "/events/%010lu.obs.json" : "/events/%010lu.json", static_cast<unsigned long>(++queueNumber));
        if (!atomicFile(path, text)) { healthy = false; return false; }
        knownPending = count + 1;
        if (!rollingObservation) ++knownCritical;
        return true;
    }
    String oldestPath() {
        String path;
#ifdef ESP8266
        Dir dir = LittleFS.openDir("/events");
        while (dir.next()) { String next = dir.fileName(); if (!next.startsWith("/")) next = "/events/" + next; if (next.endsWith(".json") && (!path.length() || next < path)) path = next; }
#else
        File dir = LittleFS.open("/events"); File entry = dir.openNextFile();
        while (entry) { String next = entry.path(); if (next.endsWith(".json") && (!path.length() || next < path)) path = next; entry.close(); entry = dir.openNextFile(); }
#endif
        return path;
    }
};

inline bool parseRecipe(JsonVariantConst value, instrument::Recipe& p) {
    return instrument::parseProgram(value, p);
}

class Digest {
#ifdef ESP8266
    br_sha256_context ctx;
#else
    mbedtls_sha256_context ctx;
#endif
public:
    Digest() {
#ifdef ESP8266
        br_sha256_init(&ctx);
#else
        mbedtls_sha256_init(&ctx); mbedtls_sha256_starts_ret(&ctx, 0);
#endif
    }
    ~Digest() {
#ifndef ESP8266
        mbedtls_sha256_free(&ctx);
#endif
    }
    void add(const void* bytes, size_t count) {
#ifdef ESP8266
        br_sha256_update(&ctx, bytes, count);
#else
        mbedtls_sha256_update_ret(&ctx, static_cast<const uint8_t*>(bytes), count);
#endif
    }
    String finish() {
        uint8_t out[32]; char hex[65];
#ifdef ESP8266
        br_sha256_out(&ctx, out);
#else
        mbedtls_sha256_finish_ret(&ctx, out);
#endif
        for (int i = 0; i < 32; ++i) snprintf(hex + 2*i, 3, "%02x", out[i]);
        return hex;
    }
};
inline bool signature(const String& message, const String& encoded) {
    String pem = readFile("/ota-public.pem", 2048);
    if (!pem.length() || encoded.length() != 344) return false;
    uint8_t sig[256]; size_t length = 0;
    // Strict, bounded base64 decoder shared by the two MCU targets.
    uint32_t bits = 0; int have = 0;
    const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (char c : encoded) {
        if (c == '=') break;
        const char* pos = strchr(alphabet, c); if (!pos || !c) return false;
        bits = (bits << 6) | (pos - alphabet); have += 6;
        if (have >= 8) { have -= 8; if (length >= sizeof(sig)) return false; sig[length++] = (bits >> have) & 255; }
    }
    if (length != 256) return false;
#ifdef ESP8266
    BearSSL::PublicKey key(pem.c_str()); BearSSL::HashSHA256 hash;
    hash.begin(); hash.add(message.c_str(), message.length()); hash.end();
    BearSSL::SigningVerifier verifier(&key);
    return verifier.verify(&hash, sig, length);
#else
    mbedtls_pk_context key; mbedtls_pk_init(&key);
    uint8_t hash[32]; mbedtls_sha256_ret(reinterpret_cast<const uint8_t*>(message.c_str()), message.length(), hash, 0);
    bool ok = mbedtls_pk_parse_public_key(&key, reinterpret_cast<const uint8_t*>(pem.c_str()), pem.length()+1) == 0 &&
        mbedtls_pk_get_type(&key) == MBEDTLS_PK_RSA && mbedtls_pk_get_bitlen(&key) == 2048 &&
        mbedtls_pk_verify(&key, MBEDTLS_MD_SHA256, hash, 32, sig, length) == 0;
    mbedtls_pk_free(&key); return ok;
#endif
}
struct Manifest { uint32_t size = 0, version = 0; String sha; };
inline bool manifest(const String& text, const char* kind, const char* hardware, Manifest& out) {
    DynamicJsonDocument d(2048);
    if (deserializeJson(d, text) || d["schema"] != 1 || strcmp(d["kind"] | "", kind) || strcmp(d["hardware"] | "", hardware)) return false;
    if (!d["size"].is<uint32_t>() || !d["version"].is<uint32_t>()) return false;
    out.size = d["size"]; out.version = d["version"]; out.sha = d["sha256"] | "";
    if (out.version <= INSTRUMENT_FIRMWARE_VERSION || out.size < 32 || out.sha.length() != 64) return false;
#ifdef ESP8266
    if (out.size > ESP.getFreeSketchSpace() || out.size > 1000000) return false;
#else
    if (out.size > 0x1b0000) return false;
#endif
    String signedText = "IMYTEST-OTA-1\n" + String(kind) + "\n" + hardware + "\n" + String(out.version) + "\n" + String(out.size) + "\n" + out.sha + "\n";
    return signature(signedText, d["signature"] | "");
}
inline bool install(Stream& stream, const Manifest& m) {
    if (!Update.begin(m.size)) return false;
    auto abortUpdate = [] {
#ifdef ESP8266
        // The final block is withheld until verification, so end(false) aborts.
        Update.end(false);
#else
        Update.abort();
#endif
    };
    Digest hash; uint8_t buffer[1024]; uint32_t received = 0, last = millis();
    while (received < m.size) {
        int available = stream.available();
        if (available <= 0) { if (instrument::elapsed(millis(), last) > 5000) { abortUpdate(); return false; } delay(1); continue; }
        size_t count = stream.readBytes(buffer, min(static_cast<uint32_t>(sizeof(buffer)), min(static_cast<uint32_t>(available), m.size - received)));
        if (!count || (!received && buffer[0] != 0xe9)) { abortUpdate(); return false; }
        hash.add(buffer, count);
        if (received + count == m.size && hash.finish() != m.sha) { abortUpdate(); return false; }
        if (Update.write(buffer, count) != count) { abortUpdate(); return false; }
        received += count; last = millis(); yield();
    }
    return Update.end(false) && Update.isFinished();
}
inline bool ota(const Network& net, const String& release, const char* kind, const char* hardware) {
    if (!safeId(release) || WiFi.status() != WL_CONNECTED) return false;
    Manifest m; String base = net.endpoint() + "/release/" + release;
    {
        Https request(net);
        if (!request.begin(net, base + "/manifest") || request.http.GET() != 200 || !manifest(request.body(2048), kind, hardware, m)) return false;
    }
    Https request(net);
    if (!request.begin(net, base + "/binary") || request.http.GET() != 200 || request.http.getSize() != static_cast<int>(m.size)) return false;
    return install(*request.http.getStreamPtr(), m);
}
}
