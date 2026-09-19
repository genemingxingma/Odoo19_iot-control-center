#pragma once
#include <ArduinoJson.h>
#include "washer_setup.hpp"

namespace instrument {
inline bool parseProgram(JsonVariantConst value, Recipe& result) {
    if (!value["schema"].is<unsigned>() || value["schema"].as<unsigned>() != 1 ||
        !value["id"].is<const char*>() || !value["revision"].is<uint32_t>()) return false;
    const char* id = value["id"];
    size_t idLength = strlen(id);
    if (!idLength || idLength > 64) return false;
    for (const char* c = id; *c; ++c)
        if (!((*c >= 'A' && *c <= 'Z') || (*c >= 'a' && *c <= 'z') ||
              (*c >= '0' && *c <= '9') || *c == '_' || *c == '-')) return false;
    if (value.containsKey("label") && !value["label"].is<const char*>()) return false;
    const char* label = value["label"] | id;
    size_t labelLength = strlen(label);
    if (!labelLength || labelLength > 48) return false;
    for (const char* c = label; *c; ++c)
        if (!((*c >= 'A' && *c <= 'Z') || (*c >= 'a' && *c <= 'z') ||
              (*c >= '0' && *c <= '9') || strchr(" _./()-", *c))) return false;
    Recipe p;
    memcpy(p.id, id, idLength + 1); memcpy(p.label, label, labelLength + 1);
    p.revision = value["revision"];
    JsonArrayConst steps = value["steps"].as<JsonArrayConst>();
    if (steps.size() < 2 || steps.size() > 32) return false;
    p.count = steps.size();
    uint8_t i = 0;
    for (JsonObjectConst obj : steps) {
        const char* kind = obj["kind"] | "";
        const char* names[] = {"home", "fill_a", "fill_b", "wash", "drain", "dry", "wait"};
        unsigned k = 0; while (k < 7 && strcmp(kind, names[k])) ++k;
        if (k == 7 || !obj["duration_s"].is<uint32_t>() || obj["duration_s"].as<uint32_t>() > 3600 ||
            (obj.containsKey("rps") && !obj["rps"].is<float>()) ||
            (obj.containsKey("reverse_s") && !obj["reverse_s"].is<uint16_t>()) ||
            (obj.containsKey("cycles") && !obj["cycles"].is<uint16_t>())) return false;
        p.steps[i++] = {static_cast<StepKind>(k), obj["duration_s"].as<uint32_t>() * 1000u,
            obj["rps"] | 0.0f, obj["reverse_s"] | uint16_t(5), obj["cycles"] | uint16_t(0)};
    }
    if (!validRecipe(p)) return false;
    result = p;
    return true;
}

// Only complete, device-bound snapshots can replace the offline catalog.
inline bool stageCatalog(JsonVariantConst value, const char* uid,
                         const ProgramLibrary& current, ProgramLibrary& staged) {
    if (!value["schema"].is<unsigned>() || value["schema"].as<unsigned>() != 1 ||
        !value["complete"].is<bool>() || !value["complete"].as<bool>() ||
        !value["device_uid"].is<const char*>() || strcmp(value["device_uid"], uid) ||
        !value["programs"].is<JsonArrayConst>() || !value["count"].is<uint16_t>()) return false;
    JsonArrayConst entries = value["programs"];
    if (entries.size() != value["count"].as<uint16_t>() || entries.size() > ProgramLibrary::Capacity) return false;
    ProgramLibrary candidate;
    candidate.items.reserve(entries.size());
    for (JsonVariantConst entry : entries) {
        Recipe p;
        if (!parseProgram(entry, p) || candidate.find(p.id) >= 0 || !candidate.put(p)) return false;
    }
    int selected = current.count ? candidate.find(current.items[current.selected].id) : -1;
    if (selected >= 0) candidate.select(selected);
    staged = std::move(candidate);
    return true;
}
}
