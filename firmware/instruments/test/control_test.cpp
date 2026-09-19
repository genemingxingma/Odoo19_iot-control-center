#include "control.hpp"
#include <cassert>
#include <cstdio>
#include <limits>
#include <initializer_list>
using namespace instrument;
Recipe program() {
    Recipe r; std::strcpy(r.id, "fixture"); r.revision = 1; r.count = 7;
    StepKind kinds[] = {StepKind::Home,StepKind::FillA,StepKind::Wait,StepKind::Wash,StepKind::Drain,StepKind::Dry,StepKind::Home};
    for(int i=0;i<7;++i) r.steps[i]={kinds[i],1000,(i==3||i==5)?1.0f:0.0f,1};
    return r;
}
Recipe typicalProgram() {
    Recipe r; std::strcpy(r.id, "general_microarray"); r.revision = 1; r.count = 9;
    StepKind kinds[] = {StepKind::Home,StepKind::FillA,StepKind::Wait,StepKind::Wash,StepKind::Drain,
                        StepKind::FillB,StepKind::Wash,StepKind::Drain,StepKind::Dry};
    for(int i=0;i<9;++i) r.steps[i]={kinds[i],1000,(kinds[i]==StepKind::Wash)?1.0f:(kinds[i]==StepKind::Dry)?10.0f:0.0f,1};
    return r;
}
int main() {
    unsigned checks = 0;
    ExchangeSchedule schedule;
    assert(!schedule.useBacklog(true)); ++checks;
    assert(schedule.useBacklog(true)); ++checks;
    assert(!schedule.useBacklog(true)); ++checks;
    assert(!schedule.useBacklog(false)); ++checks;
    assert(!schedule.useBacklog(true)); ++checks;
    Probe p{35,100,true};
    HeaterChannel h;
    assert(!h.arm(p,100)); ++checks;
    assert(h.configureProtection(600,1)); ++checks;
    h.tick(p,100); assert(!h.output && !h.enabled); ++checks;
    assert(h.arm(p,100)); h.tick(p,100); assert(h.output); ++checks;
    p.value=37; h.tick(p,100); assert(!h.output); ++checks;
    p.value=36.5; h.tick(p,100); assert(!h.output); ++checks;
    p.value=35; h.tick(p,100); assert(h.output); ++checks;
    p.valid=false; h.tick(p,101); assert(!h.output && !h.enabled && h.fault==Sensor); ++checks;
    p.valid=true; h.tick(p,102); assert(!h.output && !h.enabled); ++checks;
    for (float invalid : {-127.0f,85.0f,55.0f,std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()}) {
        p.value=35; p.valid=true; p.sampled=100; assert(h.arm(p,100)); p.value=invalid; h.tick(p,101); assert(!h.output && !h.enabled); ++checks;
    }
    p.value=35; assert(h.arm(p,100)); h.tick(p,3101); assert(h.fault==Sensor && !h.output); ++checks;
    p.sampled=0xffffff00u; assert(h.arm(p,0xffffff01u)); h.tick(p,0x100u); assert(h.output); ++checks;
    for(float target : {9.75f,50.25f,37.1f,std::numeric_limits<float>::quiet_NaN()}) { assert(!h.setTarget(target)); ++checks; }
    assert(h.setTarget(37.25)); ++checks;
    Recipe r=program(); assert(validRecipe(r)); ++checks;
    Recipe typical=typicalProgram(); assert(validRecipe(typical)); ++checks;
    Recipe refill=typical; refill.steps[7].kind=StepKind::FillA; assert(!validRecipe(refill)); ++checks;
    Washer w; assert(w.load(r)); assert(!w.start(0,false,true)); assert(!w.start(0,true,false)); ++checks;
    assert(w.start(0,true,true)); w.tick(1001,true,false); assert(!w.running && w.fault==HomeTimeout); ++checks;
    w.fault=None; assert(w.start(0,true,true)); w.tick(1,true,true); assert(w.index==1); ++checks;
    w.tick(2,true,false,false,false); assert(!w.outputs.a && !w.outputs.overflow); ++checks;
    w.tick(3,true,false,true,false); assert(w.outputs.a && !w.outputs.drain && w.outputs.overflow==255); ++checks;
    w.tick(1002,true,false,true,false); assert(!w.outputs.a && !w.outputs.drain && !w.outputs.overflow); ++checks;
    w.tick(1003,true,false,true,false); assert(w.index==1 && !w.outputs.a && !w.outputs.drain && !w.outputs.overflow); ++checks;
    w.tick(1004,true,false,true,true); assert(w.index==2); ++checks;
    w.tick(1004,true,false,true,true,false); assert(w.waiting && w.running && !w.resume(1004,false)); ++checks;
    w.tick(1005,false,false); assert(w.waiting && w.running && !w.outputs.a && w.outputs.rps==0 && !w.outputs.drain && !w.outputs.overflow); ++checks;
    assert(w.resume(1006)); w.tick(1007,true,false); assert(w.outputs.rps>0 && !w.outputs.drain && !w.outputs.overflow); ++checks;
    w.tick(1008,false,false); assert(!w.running && w.fault==DoorOpen && w.outputs.rps==0 && !w.outputs.drain && !w.outputs.overflow); ++checks;
    Washer coasting; coasting.load(r); coasting.start(0,true,true); coasting.index=2;
    coasting.tick(1,false,false,true,true,false); assert(!coasting.running && coasting.fault==DoorOpen); ++checks;
    for(int step=0;step<7;++step) {
        Washer a; a.load(r); a.start(0,true,true); a.index=step; a.entered=0;
        a.tick(1,true,false);
        assert(a.outputs.drain == (step==4 ? 150 : step==5 ? 50 : 0)); ++checks;
        assert(a.outputs.overflow == (step==1 ? 255 : step==4 ? 150 : step==5 ? 50 : 0)); ++checks;
        a.stop(); assert(!a.running && !a.outputs.a && !a.outputs.b && !a.outputs.drain && !a.outputs.overflow && !a.outputs.rps); ++checks;
    }
    for (int i=0;i<7;++i) { Recipe bad=r; bad.steps[i].duration=0; assert(!validRecipe(bad)); ++checks; }
    r.steps[0].rps=std::numeric_limits<float>::quiet_NaN(); assert(!validRecipe(r)); ++checks;
    HeaterChannel dry;
    assert(dry.configureProtection(600,1)); ++checks;
    p={30,0,true}; assert(dry.arm(p,0)); dry.tick(p,0);
    p={30.999f,599999,true}; dry.tick(p,599999); assert(dry.enabled && dry.output); ++checks;
    p.sampled=600000; dry.tick(p,600000); assert(!dry.enabled && !dry.output && dry.fault==NoTemperatureRise); ++checks;
    p={35,600001,true}; dry.tick(p,600001); assert(!dry.enabled && dry.fault==NoTemperatureRise); ++checks;
    assert(dry.arm(p,600001)); ++checks;
    HeaterChannel rising; rising.configureProtection(600,1); p={30,0,true}; rising.arm(p,0); rising.tick(p,0);
    p={31.0f,600000,true}; rising.tick(p,600000); assert(rising.enabled && rising.fault==None && rising.poweredMs==0); ++checks;
    p.sampled=1200000; rising.tick(p,1200000); assert(rising.fault==NoTemperatureRise); ++checks;
    HeaterChannel held; held.configureProtection(600,1); p={36,0,true}; held.arm(p,0); held.tick(p,0);
    p={37,500000,true}; held.tick(p,500000); assert(!held.output && held.enabled); ++checks;
    p.sampled=2400000; held.tick(p,2400000); assert(!held.output && held.enabled && held.fault==None); ++checks;
    HeaterChannel paused; paused.configureProtection(600,1); p={30,0,true}; paused.arm(p,0); paused.tick(p,0);
    paused.pause(300000); assert(!paused.output && paused.poweredMs==300000); ++checks;
    p.sampled=900000; paused.tick(p,900000); assert(paused.enabled && paused.poweredMs==300000); ++checks;
    assert(paused.setTarget(40) && paused.configureProtection(600,1)); ++checks;
    assert(!paused.configureProtection(1200,1)); ++checks;
    p.sampled=1200000; paused.tick(p,1200000); assert(paused.fault==NoTemperatureRise); ++checks;
    HeaterChannel near; near.configureProtection(600,1); p={36,0,true}; near.arm(p,0); near.tick(p,0); near.pause(100);
    p={36.5f,1000,true}; near.tick(p,1000); assert(near.output && near.enabled); ++checks;
    HeaterChannel overflow; overflow.configureProtection(600,1); p={30,0xfffffff0u,true}; overflow.arm(p,p.sampled); overflow.tick(p,p.sampled);
    p.sampled += 600000; overflow.tick(p,p.sampled); assert(overflow.fault==NoTemperatureRise); ++checks;
    Washer timed; timed.load(program()); timed.start(0,true,true); timed.index=4;
    timed.tick(999,true,false); assert(timed.outputs.drain==150 && timed.outputs.overflow==150 && timed.running); ++checks;
    timed.tick(1000,true,false); assert(timed.index==5 && !timed.outputs.drain && !timed.outputs.overflow); ++checks;
    timed.tick(1001,true,false); assert(timed.outputs.drain==50 && timed.outputs.overflow==50 && timed.outputs.rps>0); ++checks;
    timed.tick(1002,false,false); assert(!timed.outputs.drain && !timed.outputs.overflow && timed.fault==DoorOpen); ++checks;
    Recipe bFill=program(); bFill.steps[1].kind=StepKind::FillB;
    Washer b; assert(b.load(bFill)); b.start(0,true,true); b.tick(0,true,true); b.tick(1,true,false);
    assert(b.outputs.b && !b.outputs.a && !b.outputs.drain && b.outputs.overflow==255); ++checks;
    assert(pwmPercent(0)==0 && pwmPercent(50)==128 && pwmPercent(60)==153 && pwmPercent(80)==204 && pwmPercent(100)==255 && pwmPercent(255)==255); ++checks;
    Washer manual; manual.load(program()); manual.start(0,true,true); manual.index=2;
    manual.tick(20000000,true,false); assert(manual.waiting && manual.running && manual.index==2); ++checks;
    manual.tick(20000001,true,false,true,true,false);
    assert(manual.waiting && !manual.outputs.a && !manual.outputs.b && !manual.outputs.drain && !manual.outputs.overflow && !manual.outputs.rps); ++checks;
    assert(!manual.resume(20000002,false) && manual.index==2); ++checks;
    assert(manual.resume(20000003,true) && manual.index==3); ++checks;
    manual.tick(20000004,true,false); assert(manual.running && manual.outputs.rps>0 && manual.activeMs==1); ++checks;
    Washer wrap; wrap.load(program()); wrap.start(0xffffff00u,true,true); wrap.index=2;
    wrap.tick(0x100u,true,false); assert(wrap.waiting && wrap.resume(0x101u)); ++checks;
    Recipe longPauses=program(); longPauses.count=8;
    for (uint8_t i=1;i<7;++i) longPauses.steps[i]={StepKind::Wait,3600000,0,1};
    longPauses.steps[7]={StepKind::Home,1000,0,1};
    assert(validRecipe(longPauses)); ++checks;
    Washer bounded; bounded.load(program()); bounded.start(0,true,true); bounded.index=3;
    bounded.tick(15000001,true,false); assert(!bounded.running && bounded.fault==RunTimeout && !bounded.outputs.overflow); ++checks;
    int32_t expected[] = {0,533,1067,1600,2133,2667};
    for (uint8_t slot=0;slot<6;++slot) {
        int32_t delta=slotDelta(0,slot,0);
        assert((delta+3200)%3200 == expected[slot]); ++checks;
        assert(slotDelta(expected[slot],slot,0)==0); ++checks;
        assert(slotDelta(expected[slot]+6400,slot,0)==0); ++checks;
        assert(slotDelta(expected[slot]-6400,slot,0)==0); ++checks;
        assert(slotDelta(expected[slot]+100,slot,100)==0); ++checks;
    }
    assert(slotDelta(2667,0,0)==533 && slotDelta(0,5,0)==-533); ++checks;
    assert(slotDelta(0,6,0)==0 && slotDelta(0,0,-1)==0 && slotDelta(0,0,3200)==0); ++checks;
    BalancedLoading loading;
    assert(!loading.start(0,0,0,160,false,true,true) && !loading.start(0,0,0,160,true,false,true) && !loading.start(0,0,0,160,true,true,false)); ++checks;
    for (int32_t bad : {-1,3200}) { assert(!loading.start(0,0,bad,160,true,true,true)); ++checks; }
    for (uint32_t bad : {0u,31u,3201u}) { assert(!loading.start(0,0,0,bad,true,true,true)); ++checks; }
    assert(!loading.start(0,-1,0,160,true,true,true) && !loading.start(0,3200,0,160,true,true,true)); ++checks;
    assert(!loading.prime(0,0,false,true) && !loading.prime(0,0,true,false)); ++checks;
    assert(!loading.prime(123,0,true,true) && loading.currentSlot()==255 && loading.nextSlot()==0); ++checks;
    assert(loading.start(100,123,0,160,true,true,true) && loading.distance==-123 && loading.target==0); ++checks;
    assert(!loading.complete(124,true,0) && !loading.complete(125,false,0) && !loading.complete(125,true,1)); ++checks;
    assert(loading.currentSlot()==255 && loading.active); ++checks;
    assert(loading.complete(1000,true,0) && loading.currentSlot()==0 && loading.nextDegrees()==180); ++checks;
    assert(!loading.start(1100,1,0,160,true,true,true)); ++checks;
    assert(loading.start(1100,0,0,160,true,true,true) && loading.distance==1600 && loading.timeoutMs==12000); ++checks;
    assert(!loading.start(1200,0,0,160,true,true,true) && loading.pendingCursor==1); ++checks;
    assert(!loading.expired(13099) && loading.expired(13100) && !loading.complete(13100,true,1600)); ++checks;
    loading.reset(); assert(!loading.active && loading.currentSlot()==255 && !loading.expired(14000)); ++checks;
    assert(loading.start(0xfffffff0u,0,0,32,true,true,true) && loading.timeoutMs==52000); ++checks;
    assert(loading.complete(0x100u,true,1600) && loading.currentSlot()==3 && loading.nextDegrees()==60); ++checks;
    for (int32_t offset : {0,1,533,1599,3199}) {
        loading.reset(); assert(loading.prime(offset,offset,true,true)); ++checks;
        int32_t position=offset, total=0; uint8_t order[]={3,4,1,2,5,0};
        for (unsigned i=0;i<12;++i) {
            assert(loading.nextDegrees()==(i%2==0 ? 180u : 60u)); ++checks;
            assert(loading.start(100000+i*20000,position,offset,160,true,true,true)); ++checks;
            assert(i%2==0 ? loading.distance==1600 : loading.distance==533 || loading.distance==534); ++checks;
            total+=loading.distance;
            assert(!loading.complete(100100+i*20000,false,loading.target) && loading.active); ++checks;
            assert(loading.complete(loading.began+loading.timeoutMs-500,true,loading.target)); ++checks;
            position=(loading.target+3200)%3200;
            assert(loading.currentSlot()==order[i%6] && slotDelta(position,order[i%6],offset)==0 && !loading.active); ++checks;
        }
        assert(position==offset && total==12800); ++checks;
    }
    assert(WasherMotorProfile::HomeHz==3200 && WasherMotorProfile::MotionAcceleration==3200); ++checks;
    loading.reset();
    assert(loading.start(100,0,0,WasherMotorProfile::LoadingHz,true,true,true) && loading.distance==1600 && loading.timeoutMs==2500); ++checks;
    assert(WasherMotorProfile::LoadingAcceleration==3200 && WasherMotorProfile::FillOverflowPwm==255 && WasherMotorProfile::SpinDrainPwm==50); ++checks;
    std::printf("INSTRUMENT_NATIVE_CHECKS_OK %u\n",checks);
}
