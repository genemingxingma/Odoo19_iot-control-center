#include "program_catalog.hpp"
#include "pump_timing.hpp"
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
    DynamicJsonDocument program(2048);
    assert(!deserializeJson(program, R"({"schema":2,"id":"test","revision":2,"steps":[{"kind":"home","duration_s":10},{"kind":"fill_a"},{"kind":"drain","duration_s":20},{"kind":"fill_b"},{"kind":"drain","duration_s":20}]})"));
    Recipe symbolic, resolved;
    assert(parseProgram(program, symbolic) && symbolic.schema == 2 && symbolic.steps[1].duration == 0);
    PumpTiming timing;
    assert(!timing.resolve(symbolic, resolved));
    timing = {1, 12, 0}; assert(!timing.resolve(symbolic, resolved));
    timing = {1, 12, 24}; assert(timing.resolve(symbolic, resolved));
    assert(resolved.steps[1].duration == 12000 && resolved.steps[3].duration == 24000);
    assert(symbolic.schema == 2 && symbolic.steps[1].duration == 0);
    timing.a = 50; assert(resolved.steps[1].duration == 12000);
    Washer machine; assert(machine.load(symbolic) && !machine.start(0,true,true));
    assert(machine.load(resolved) && machine.start(0,true,true));
    machine.tick(1,true,true); machine.tick(2,true,true);
    assert(machine.outputs.a && !machine.outputs.b && machine.outputs.overflow && !machine.outputs.drain);
    machine.tick(12001,true,true); assert(!machine.outputs.a);
    timing.a = 301; assert(!timing.resolve(symbolic, resolved));
    timing = {0,12,24}; assert(!timing.resolve(symbolic, resolved));
    timing = {2147483648u,12,24}; assert(!timing.valid());
    program["steps"][1]["duration_s"] = 15; assert(!parseProgram(program,symbolic));
    program["steps"][1].remove("duration_s"); program["schema"] = 3; assert(!parseProgram(program,symbolic));
    program["schema"] = 1; program["steps"][1]["duration_s"] = 15; program["steps"][3]["duration_s"] = 15;
    assert(parseProgram(program,symbolic)); timing = {1,12,24}; assert(!timing.resolve(symbolic,resolved));
    // Full offline field-test sequence. No hardware or network is involved here.
    assert(!deserializeJson(program, R"({"schema":2,"id":"demo","revision":3,"steps":[{"kind":"home","duration_s":10},{"kind":"fill_a"},{"kind":"wait","duration_s":1},{"kind":"wash","duration_s":30,"rps":1,"reverse_s":3,"cycles":5},{"kind":"drain","duration_s":20},{"kind":"fill_b"},{"kind":"wash","duration_s":30,"rps":1,"reverse_s":3,"cycles":5},{"kind":"drain","duration_s":20},{"kind":"dry","duration_s":30,"rps":10}]})"));
    assert(parseProgram(program,symbolic));
    timing={2,10,10}; assert(timing.resolve(symbolic,resolved));
    Washer field; assert(field.load(resolved) && field.start(100,true,true));
    field.tick(101,true,true); assert(field.index==1);
    field.tick(102,true,true,false,false); assert(!field.outputs.a);
    field.tick(103,true,true,true,false);
    assert(field.outputs.a && field.outputs.overflow==WasherMotorProfile::FillOverflowPwm && !field.outputs.drain);
    field.tick(10102,true,true,true,false); assert(field.index==1 && !field.outputs.a);
    field.tick(10103,true,true,true,true); assert(field.index==2);
    field.tick(10104,true,true); assert(field.waiting);
    field.tick(3600104,true,true); // An hour waiting must not continue automatically.
    assert(field.index==2 && field.waiting && !field.outputs.a && !field.outputs.b && !field.outputs.drain && !field.outputs.overflow && field.outputs.rps==0);
    assert(!field.resume(3600105,false) && field.resume(3600106,true));
    for (unsigned stepIndex=3;stepIndex<9;++stepIndex) {
        assert(field.index==stepIndex);
        uint32_t began=field.entered;
        field.tick(began+1,true,true);
        if (stepIndex==3 || stepIndex==6) {
            assert(field.outputs.rps==1 && !field.outputs.drain);
            field.tick(began+3000,true,true); assert(field.outputs.rps==-1);
        } else if (stepIndex==4 || stepIndex==7) {
            assert(field.outputs.drain==WasherMotorProfile::DrainPwm && field.outputs.overflow==field.outputs.drain);
        } else if (stepIndex==5) {
            assert(field.outputs.b && !field.outputs.a && field.outputs.overflow==WasherMotorProfile::FillOverflowPwm && !field.outputs.drain);
        } else {
            assert(field.outputs.rps==10 && field.outputs.drain==WasherMotorProfile::SpinDrainPwm && field.outputs.overflow==field.outputs.drain);
        }
        field.tick(began+resolved.steps[stepIndex].duration,true,true);
    }
    assert(field.finishing && !field.completed);
    field.tick(field.entered+1,true,true,true,true,false);
    assert(field.running && field.outputs.drain==WasherMotorProfile::SpinDrainPwm);
    field.tick(field.entered+2,true,true,true,true,true);
    assert(field.completed && !field.running && !field.outputs.drain && !field.outputs.overflow && field.outputs.rps==0);
    // STOP is terminal for this run, never pause/resume or a queued restart.
    assert(field.start(5000000,true,true)); field.stop();
    assert(!field.resume(5000001,true)); field.tick(5000002,true,true);
    assert(!field.running && !field.outputs.a && !field.outputs.b && !field.outputs.drain && !field.outputs.overflow);
    std::puts("WASHER_CATALOG_AND_PUMP_TIMING_TESTS_OK");
}
