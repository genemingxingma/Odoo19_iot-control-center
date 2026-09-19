#include "tjc_ui.hpp"
#include <cassert>
#include <fstream>
#include <iostream>

int touch(tjc::Display& display, unsigned x, unsigned y, bool press, uint32_t now) {
    uint8_t data[] = {0x67, uint8_t(x>>8), uint8_t(x), uint8_t(y>>8), uint8_t(y), uint8_t(press),255,255,255};
    int result = -1;
    for(auto byte:data) { int r=display.touch(byte,now); if(r>=0)result=r; }
    return result;
}
int main(int argc, char** argv) {
    tjc::Display display;
    assert(!display.acceptsAction(1000));
    assert(touch(display,100,420,true,100)==-1);
    assert(touch(display,100,420,false,300)==0);
    assert(touch(display,650,420,true,400)==2);
    assert(touch(display,650,420,false,500)==-1);
    assert(touch(display,100,420,true,600)==-1);
    assert(touch(display,400,420,false,700)==-1);
    assert(touch(display,400,420,true,800)==-1);
    assert(touch(display,400,420,false,5900)==-1);
    assert(touch(display,900,420,true,6000)==-1);
    display.touch(0x67,7000); display.touch(0,7200);
    assert(!display.receivingTouch());
    tjc::View view;
    view.state="RUNNING"; view.program="Array Wash A / r2";
    view.step="4/8  Wash"; view.temperature="37.2 C"; view.remaining="Step 01:24";
    view.notice="Run in progress. Keep the lid closed."; view.progress=42;
    view.ready=true; view.running=true; view.door=true;
    display.render(view);
    assert(!display.acceptsAction(1000));
    HardwareSerial serial;
    unsigned ticks=0;
    while(display.busy()) { display.tick(serial,100); assert(++ticks<40); }
    assert(!display.acceptsAction(849));
    assert(display.acceptsAction(850));
    assert(serial.output.find("t_state") == std::string::npos);
    assert(serial.output.find("STOP") != std::string::npos);
    assert(serial.output.find("Array Wash A / r2") != std::string::npos);
    assert(serial.output.find("fill 0,0,800,62,"+std::to_string(tjc::Header)) != std::string::npos);
    assert(serial.output.find("fill 0,62,800,4,"+std::to_string(tjc::Blue)) != std::string::npos);
    assert(serial.output.find("xstr 24,10,472,42,"+std::to_string(tjc::Font)) != std::string::npos);
    assert(serial.output.find(","+std::to_string(tjc::Button)+",1,1,1,\"PROGRAMS\"") != std::string::npos);
    assert(serial.output.find("Lid closed") == std::string::npos);
    assert(serial.output.find("read only") == std::string::npos);
    if(argc>1) {
        std::ofstream out(argv[1]);
        std::string commands=serial.output;
        size_t found;
        while((found=commands.find("\xff\xff\xff"))!=std::string::npos) commands.replace(found,3,"\n");
        out << commands;
    }
    display.page=1;
    assert(!display.acceptsAction(1600));
    display.render(view);
    assert(!display.acceptsAction(1600));
    while(display.busy()) display.tick(serial,1000);
    assert(!display.acceptsAction(1749));
    assert(display.acceptsAction(1750));
    unsigned checks=24;
    assert(touch(display,100,180,true,1900)==-1 && touch(display,100,180,false,1950)==-1); ++checks;
    display.page=4; display.dirty=true;
    view.state="WAITING"; view.waiting=true; view.openRotor=true; view.door=false;
    view.loadingReady=true; view.slot=0; view.targetSlot=3; view.loadingDegrees=180;
    view.notice="Check stopped, then load. Tap NEXT once to index. Check balance before CONTINUE.";
    HardwareSerial loading;
    display.render(view);
    assert(!display.acceptsAction(2000)); ++checks;
    while(display.busy()) display.tick(loading,2000);
    assert(!display.acceptsAction(2749) && display.acceptsAction(2750)); ++checks;
    assert(loading.output.find("PAUSED / LOAD SLIDES")!=std::string::npos); ++checks;
    assert(loading.output.find("Pumps remain OFF")!=std::string::npos); ++checks;
    assert(loading.output.find("Check balance before CONTINUE")!=std::string::npos); ++checks;
    assert(loading.output.find("NEXT +180")!=std::string::npos && loading.output.find("HOLD TO MOVE")==std::string::npos); ++checks;
    for(unsigned slot=0;slot<6;++slot) {
        unsigned x=100+(slot%3)*256, y=180+(slot/3)*72;
        assert(touch(display,x,y,true,2800)==-1); ++checks;
        assert(touch(display,x,y,false,2900)==-1); ++checks;
        assert(loading.output.find("SLOT "+std::to_string(slot+1))!=std::string::npos); ++checks;
    }
    assert(touch(display,270,180,true,3000)==-1 && touch(display,270,180,false,3050)==-1); ++checks;
    assert(touch(display,400,420,true,3100)==-1); ++checks;
    assert(touch(display,400,420,true,3200)==-1); ++checks;
    assert(touch(display,400,420,false,3300)==1); ++checks;
    assert(touch(display,400,420,false,3400)==-1); ++checks;
    assert(touch(display,650,420,true,3500)==2); ++checks;
    assert(touch(display,650,420,false,3600)==-1); ++checks;
    assert(touch(display,100,420,true,3700)==-1 && touch(display,100,420,false,3800)==0); ++checks;
    view.moving=true;
    display.render(view); while(display.busy()) display.tick(loading,4000);
    assert(touch(display,400,420,true,4800)==-1 && touch(display,400,420,false,4900)==-1); ++checks;
    assert(touch(display,100,420,true,4800)==-1 && touch(display,100,420,false,4900)==-1); ++checks;
    assert(touch(display,650,420,true,4800)==2); ++checks;
    touch(display,400,420,true,4950);
    view.moving=false; view.slot=3; view.targetSlot=4; view.loadingDegrees=60;
    display.render(view); while(display.busy()) display.tick(loading,5000);
    assert(touch(display,400,420,false,5800)==-1); ++checks;
    assert(touch(display,400,420,true,5900)==-1 && touch(display,400,420,false,5950)==1); ++checks;
    assert(loading.output.find("NEXT +60")!=std::string::npos); ++checks;
    touch(display,400,420,true,6000); // Do not replay this press after a disabled frame.
    view.loadingReady=false;
    display.render(view); while(display.busy()) display.tick(loading,6100);
    assert(touch(display,400,420,false,7000)==-1); ++checks;
    assert(touch(display,400,420,true,7100)==-1 && touch(display,400,420,false,7150)==-1); ++checks;
    assert(loading.output.find("NOT CALIBRATED")!=std::string::npos); ++checks;
    view.loadingReady=true; view.slot=instrument::BalancedLoading::Unknown;
    display.render(view); while(display.busy()) display.tick(loading,7200);
    assert(loading.output.find("ALIGN START")!=std::string::npos); ++checks;
    // A finger held across a page transition must not activate its new action.
    touch(display,100,420,true,8100);
    display.page=0; display.render(view);
    assert(touch(display,100,420,false,8200)==-1); ++checks;
    if(argc>1) {
        std::ofstream out(std::string(argv[1])+".loading.txt");
        std::string commands=loading.output;
        size_t found;
        while((found=commands.find("\xff\xff\xff"))!=std::string::npos) commands.replace(found,3,"\n");
        out << commands;
    }
    while(display.busy()) display.tick(loading,8300);
    tjc::Display simple;
    HardwareSerial overview;
    simple.render(view); while(simple.busy()) simple.tick(overview,8400);
    assert(overview.output.find("Open rotor")==std::string::npos); ++checks;
    assert(overview.output.find("Lid open")==std::string::npos); ++checks;
    simple.page=2; simple.dirty=true;
    HardwareSerial care;
    simple.render(view); while(simple.busy()) simple.tick(care,8500);
    assert(care.output.find("no PSRAM")==std::string::npos); ++checks;
    assert(care.output.find("RESET FAULT")!=std::string::npos); ++checks;
    display.page=5; view.programCount=2; view.selectedProgram=1;
    view.programs[0]="Program 7"; view.programs[1]="Program 8";
    view.libraryPage=2; view.libraryPages=3;
    HardwareSerial library;
    display.render(view); while(display.busy()) display.tick(library,9000);
    assert(library.output.find("Program 8")!=std::string::npos); ++checks;
    assert(library.output.find("3 / 3")!=std::string::npos); ++checks;
    assert(library.output.find("REMOVE")==std::string::npos); ++checks;
    for (unsigned i=0;i<3;++i) {
        assert(touch(display,100,140+i*76,true,9200)==-1); ++checks;
        assert(touch(display,100,140+i*76,false,9250)==int(10+i)); ++checks;
    }
    assert(touch(display,100,370,true,9300)==-1 && touch(display,100,370,false,9350)==3); ++checks;
    assert(touch(display,600,370,true,9400)==-1 && touch(display,600,370,false,9450)==4); ++checks;
    display.page=7; view.passwordField=true; view.wifiEntry="********";
    HardwareSerial keyboard;
    display.render(view); while(display.busy()) display.tick(keyboard,10000);
    assert(!display.acceptsAction(10119) && display.acceptsAction(10120)); ++checks;
    assert(keyboard.output.find("ENTER WI-FI PASSWORD")!=std::string::npos); ++checks;
    for (unsigned i=0;i<40;++i) {
        unsigned x=40+(i%10)*75, y=160+(i/10)*50;
        assert(touch(display,x,y,true,10200)==-1); ++checks;
        assert(touch(display,x,y,false,10250)==int(10+i)); ++checks;
    }
    assert(touch(display,775,160,true,10300)==-1 && touch(display,775,160,false,10350)==-1); ++checks;
    assert(touch(display,650,420,true,10400)==2); ++checks;
    assert(touch(display,650,420,false,10450)==-1); ++checks;
    std::cout << "INSTRUMENT_UI_CHECKS_OK " << checks << "\n";
}
