#include "washer_setup.hpp"
#include <cassert>
#include <cstdio>
#include <string>
using namespace instrument;
Recipe program(unsigned i) {
    Recipe p; snprintf(p.id,sizeof(p.id),"program_%u",i); strcpy(p.label,"Synthetic fixture");
    p.revision=1; p.count=2; p.steps[0].kind=p.steps[1].kind=StepKind::Home; return p;
}
int main() {
    WasherAuthorization authorization;
    assert(!authorization.configured() && !authorization.allowed());
    authorization.configure(false, true, true);
    assert(!authorization.configured() && !authorization.allowed());
    authorization.configure(true, false, true);
    assert(authorization.fieldTest && !authorization.commissioned);
    assert(authorization.allowed());
    authorization.configure(true, false, true);
    assert(authorization.allowed());
    authorization.configure(true, true, true);
    assert(authorization.allowed());
    assert(!authorization.fieldTest);

    ProgramLibrary library;
    for (unsigned i=0;i<8;++i) assert(library.put(program(i)));
    assert(library.count==8 && library.select(7) && !library.select(8));
    Recipe changed=program(7); changed.revision=2; changed.steps[0].duration=9000;
    assert(library.put(changed) && library.count==8 && library.selected==7);
    assert(!library.put(program(7)));
    changed.steps[0].duration=8000; assert(!library.put(changed));
    ProgramLibrary replacement;
    assert(replacement.put(program(2)) && replacement.put(program(4)));
    assert(library.count==8); // A staged snapshot has no effect before commit.
    library=replacement; assert(library.count==2 && library.find("program_7")==-1);
    library=ProgramLibrary(); assert(library.count==0);
    for (unsigned i=0;i<ProgramLibrary::Capacity;++i) assert(library.put(program(i)));
    assert(!library.put(program(200)) && library.count==ProgramLibrary::Capacity);

    Startup startup;
    assert(startup.readyToStart(true,true,true,true));
    assert(!startup.readyToStart(false,true,true,true));
    assert(!startup.readyToStart(true,false,true,true));
    assert(!startup.readyToStart(true,true,false,true));
    assert(!startup.readyToStart(true,true,true,false));
    startup.stop();
    assert(!startup.readyToStart(true,true,true,true));
    startup = Startup();
    assert(!startup.start(0,false) && startup.phase==Startup::Pending);
    assert(startup.start(100,true) && startup.drain()==0);
    assert(!startup.start(200,true));
    assert(startup.tick(9999,true,false,true)==None && startup.phase==Startup::Homing);
    assert(startup.tick(10100,true,false,true)==HomeTimeout && startup.phase==Startup::Stopped);
    assert(startup.tick(999999,true,true,true)==None && startup.phase==Startup::Stopped);
    assert(startup.start(20000,true));
    assert(startup.tick(21000,true,true,false)==None && startup.phase==Startup::Homing);
    assert(startup.tick(21100,true,true,true)==None && startup.phase==Startup::Draining && startup.drain()==150);
    assert(startup.tick(41099,true,true,true)==None && startup.phase==Startup::Draining);
    assert(startup.tick(41100,true,true,true)==None && startup.phase==Startup::Ready && startup.drain()==0);
    assert(!startup.start(50000,true));
    startup.stop(); assert(startup.phase==Startup::Stopped);
    assert(startup.start(50001,true));
    startup=Startup(); assert(startup.start(0xfffffff0u,true));
    assert(startup.tick(0x100,true,true,true)==None && startup.phase==Startup::Draining);
    startup.stop(); assert(startup.phase==Startup::Stopped && startup.drain()==0);
    assert(startup.start(1000,true));
    assert(startup.tick(1001,false,true,true)==DoorOpen && startup.phase==Startup::Stopped);

    WifiDraft wifi;
    assert(!wifi.valid());
    for (unsigned mode=0;mode<3;++mode) assert(strlen(WifiDraft::keys(mode))==40);
    for (char c:std::string("Test network")) assert(wifi.append(c));
    assert(wifi.valid()); // Explicitly empty password is an open network.
    wifi.passwordField=true; assert(wifi.append('x') && !wifi.valid());
    wifi.backspace(); assert(wifi.valid());
    for (unsigned i=0;i<64;++i) assert(wifi.append('a'));
    assert(wifi.valid() && !wifi.append('a'));
    wifi.backspace(); assert(wifi.append('!') && !wifi.valid());
    wifi.clear(); assert(!wifi.valid() && !wifi.password[0] && !wifi.passwordField);
    for (unsigned i=0;i<32;++i) assert(wifi.append('s'));
    assert(!wifi.append('s') && !wifi.append('\n'));
    wifi.beginEdit(false); wifi.backspace(); wifi.endEdit(false);
    assert(strlen(wifi.ssid)==32 && !wifi.previousField[0]);
    wifi.beginEdit(false); wifi.backspace(); wifi.endEdit(true);
    assert(strlen(wifi.ssid)==31 && !wifi.previousField[0]);
    wifi.beginEdit(true); assert(wifi.append('x')); wifi.endEdit(false);
    assert(!wifi.password[0] && strlen(wifi.ssid)==31 && !wifi.previousField[0]);

    Recipe cycles=program(0); cycles.count=5;
    cycles.steps[1]={StepKind::FillA,1000,0,5};
    cycles.steps[2]={StepKind::Wash,12000,1,3,2};
    cycles.steps[3]={StepKind::Drain,1000,0,5};
    cycles.steps[4]={StepKind::Home,10000,0,5};
    assert(validRecipe(cycles));
    cycles.steps[2].duration=11000; assert(!validRecipe(cycles));
    cycles.steps[2].duration=12000; cycles.steps[3].cycles=1; assert(!validRecipe(cycles));
    cycles.steps[3].cycles=0;
    Washer w; assert(w.load(cycles) && w.start(0,true,true));
    w.tick(1,true,true); w.tick(1002,true,true); // Home and fill completed.
    assert(w.index==2);
    w.tick(1003,true,true); assert(w.outputs.rps==1);
    w.tick(4002,true,true); assert(w.outputs.rps==-1);
    w.tick(7002,true,true); assert(w.outputs.rps==1);
    w.tick(10002,true,true); assert(w.outputs.rps==-1);
    w.tick(13002,true,true); assert(w.index==3 && w.outputs.rps==0);
    std::puts("WASHER_SETUP_TESTS_OK");
}
