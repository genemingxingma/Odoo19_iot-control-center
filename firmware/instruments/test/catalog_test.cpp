#include "program_catalog.hpp"
#include <cassert>
#include <cstdio>
#include <string>
using namespace instrument;
void addProgram(JsonArray entries, unsigned id, unsigned revision=1) {
    JsonObject p=entries.createNestedObject();
    p["schema"]=1; p["id"]="program_"+std::to_string(id);
    p["label"]="Offline wash"; p["revision"]=revision;
    JsonArray steps=p.createNestedArray("steps");
    for (unsigned i=0;i<2;++i) {
        JsonObject step=steps.createNestedObject(); step["kind"]="home"; step["duration_s"]=10;
    }
}
int main() {
    DynamicJsonDocument doc(32768);
    doc["schema"]=1; doc["complete"]=true; doc["device_uid"]="fixture"; doc["count"]=8;
    JsonArray entries=doc.createNestedArray("programs");
    for (unsigned i=0;i<8;++i) addProgram(entries,i);
    ProgramLibrary current, staged;
    assert(stageCatalog(doc,"fixture",current,staged));
    assert(current.count==0 && staged.count==8);
    current=std::move(staged); assert(current.select(7));
    // Add, replace, and remove are one snapshot, preserving selection by identity.
    entries.clear(); addProgram(entries,7,2); addProgram(entries,8); doc["count"]=2;
    assert(stageCatalog(doc,"fixture",current,staged));
    assert(current.count==8 && current.items[7].revision==1);
    assert(staged.count==2 && staged.selected==0 && staged.items[0].revision==2);
    assert(staged.find("program_0")==-1 && staged.find("program_8")==1);
    // Failure at any point leaves both the current and previously staged lists intact.
    doc["count"]=3; assert(!stageCatalog(doc,"fixture",current,staged));
    doc["count"]=2; doc["complete"]=false; assert(!stageCatalog(doc,"fixture",current,staged));
    doc["complete"]=1; assert(!stageCatalog(doc,"fixture",current,staged));
    doc["complete"]=true; assert(!stageCatalog(doc,"other_device",current,staged));
    entries[1]["label"]=false; assert(!stageCatalog(doc,"fixture",current,staged));
    entries[1]["label"]="Offline wash";
    entries[1]["revision"]=0; assert(!stageCatalog(doc,"fixture",current,staged));
    entries[1]["revision"]=1; entries[1]["id"]="program_7";
    assert(!stageCatalog(doc,"fixture",current,staged));
    assert(current.count==8 && staged.count==2 && staged.items[0].revision==2);
    // Only an authenticated complete empty snapshot is a deletion, not absent data.
    assert(!stageCatalog(JsonVariantConst(),"fixture",current,staged));
    entries.clear(); doc["count"]=0;
    assert(stageCatalog(doc,"fixture",current,staged) && staged.count==0);
    assert(current.count==8);
    current=std::move(staged); assert(current.count==0);
    std::puts("WASHER_CATALOG_TESTS_OK");
}
