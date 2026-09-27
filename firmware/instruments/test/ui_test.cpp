#include "tjc_ui.hpp"
#include <cassert>
#include <fstream>
#include <iostream>

std::string flush(tjc::Display& display, uint32_t now) {
    HardwareSerial serial;
    unsigned ticks = 0;
    while (display.busy()) {
        display.tick(serial, now);
        assert(++ticks < 40);
    }
    return serial.output;
}

int main(int argc, char** argv) {
    unsigned checks = 0;
    tjc::Display display;
    tjc::View view;
    view.program = "General Microarray V1.0 / r3";
    view.notice = "Choose a program, then review before starting.";
    display.render(view);
    std::string home = flush(display, 1000);
    assert(home.find("page page1") != std::string::npos); ++checks;
    assert(home.find("t1.txt=\"General Microarray V1.0 / r3\"") != std::string::npos); ++checks;
    assert(home.find("cls ") == std::string::npos && home.find("fill ") == std::string::npos &&
           home.find("xstr ") == std::string::npos); ++checks;
    assert(!display.acceptsAction(1149) && display.acceptsAction(1150)); ++checks;
    display.render(view);
    assert(!display.busy()); ++checks;

    view.notice = "Program synchronized.";
    display.dirty = true;
    display.render(view);
    std::string update = flush(display, 1200);
    assert(update.find("page page1") == std::string::npos); ++checks;
    assert(update.find("t2.txt=\"Program synchronized.\"") != std::string::npos); ++checks;
    assert(update.find("t1.txt") == std::string::npos); ++checks;

    view.startup = true; view.step = "Starting automatic preparation";
    view.notice = "Keep hands clear. STOP cancels initialization."; view.remaining = "Starting now";
    display.dirty = true; display.render(view);
    std::string startup = flush(display, 1300);
    assert(startup.find("page page4") != std::string::npos); ++checks;
    assert(startup.find("Starting automatic preparation") != std::string::npos); ++checks;
    view.startup = false;

    display.page = tjc::Programs;
    view.programCount = 12; view.selectedProgram = 4;
    view.programChoice = "Program 5 / r2";
    display.dirty = true; display.render(view);
    std::string programs = flush(display, 2000);
    assert(programs.find("page page3") != std::string::npos); ++checks;
    assert(programs.find("t1.txt=\"Program 5 / r2\"") != std::string::npos); ++checks;
    assert(programs.find("Program 5 of 12\\rUse Previous and Next") != std::string::npos); ++checks;
    assert(programs.find("b1.bco=" + std::to_string(tjc::Blue)) != std::string::npos); ++checks;

    display.page = tjc::Review; view.ready = true; view.notice = "Fill A: 10 s / B: 12 s";
    display.dirty = true; display.render(view);
    std::string ready = flush(display, 3000);
    assert(ready.find("page page5") != std::string::npos); ++checks;
    assert(ready.find("b0.bco=" + std::to_string(tjc::Blue)) != std::string::npos); ++checks;

    view.running = true; view.step = "Step 4 of 9 - Wash"; view.cycle = "Cycle 2 of 5";
    view.remaining = "Left 0:24"; view.temperature = "25.4 C";
    display.dirty = true; display.render(view);
    std::string running = flush(display, 4000);
    assert(running.find("page page6") != std::string::npos); ++checks;
    assert(running.find("Step 4 of 9 - Wash\\rCycle 2 of 5\\rLeft 0:24\\rTemperature 25.4 C") != std::string::npos); ++checks;

    view.waiting = true; view.loadingReady = true; view.moving = false;
    view.slot = 0; view.targetSlot = 3; view.loadingDegrees = 180;
    view.notice = "Load an opposite pair, then continue.";
    display.dirty = true; display.render(view);
    std::string loading = flush(display, 5000);
    assert(loading.find("page page7") != std::string::npos); ++checks;
    assert(loading.find("b0.txt=\"Next Position\"") != std::string::npos); ++checks;
    assert(loading.find("Current slot 1 | Next 4 (180 deg)\\rLoad an opposite pair") != std::string::npos); ++checks;

    view.running = false; view.waiting = false; view.completed = false;
    display.page = tjc::Wifi; view.wifiSsid = "Laboratory WiFi"; view.wifiPassword = "secretpass";
    display.dirty = true; display.render(view);
    std::string wifi = flush(display, 6000);
    assert(wifi.find("page page8") != std::string::npos); ++checks;
    assert(wifi.find("t1.txt=\"Laboratory WiFi\"") != std::string::npos); ++checks;
    assert(wifi.find("t2.txt=\"secretpass\"") != std::string::npos); ++checks;

    display.page = tjc::PumpTimes; view.pumpA = 10; view.pumpB = 12;
    display.dirty = true; display.render(view);
    std::string pumps = flush(display, 7000);
    assert(pumps.find("page page9") != std::string::npos); ++checks;
    assert(pumps.find("t1.txt=\"Buffer A\\r10 s\"") != std::string::npos); ++checks;
    assert(pumps.find("t2.txt=\"Buffer B\\r12 s\"") != std::string::npos); ++checks;

    view.fault = true; view.notice = "Homing timed out. Check the home sensor.";
    display.dirty = true; display.render(view);
    std::string fault = flush(display, 8000);
    assert(fault.find("page page11") != std::string::npos); ++checks;
    assert(fault.find("Homing timed out") != std::string::npos); ++checks;

    view.fault = false; view.completed = true; display.page = tjc::Overview;
    display.dirty = true; display.render(view);
    std::string finished = flush(display, 9000);
    assert(finished.find("page page12") != std::string::npos); ++checks;
    assert(finished.find("Program finished") != std::string::npos); ++checks;

    assert(display.touch(0x67, 9100) == -1 && !display.receivingTouch()); ++checks;
    display.invalidate(); display.render(view);
    std::string reconnect = flush(display, 10000);
    assert(reconnect.find("page page12") != std::string::npos); ++checks;

    view.completed = false; view.program = "Quote \" and slash \\";
    display.page = tjc::Overview; display.dirty = true; display.render(view);
    std::string escaped = flush(display, 11000);
    assert(escaped.find("Quote ' and slash /") != std::string::npos); ++checks;

    if (argc > 1) {
        std::ofstream out(argv[1]);
        std::string commands = home + startup + programs + ready + running + loading + wifi + pumps + fault + finished;
        size_t found;
        while ((found = commands.find("\xff\xff\xff")) != std::string::npos) commands.replace(found, 3, "\n");
        out << commands;
    }
    std::cout << "NATIVE_UI_CHECKS_OK " << checks << "\n";
}
