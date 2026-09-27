#include "heater_panel.hpp"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
using namespace instrument;
struct Display {
    int x=0,y=0,size=1;
    std::vector<std::string> lines;
    void clearDisplay() { lines.clear(); }
    void setTextColor(int) {}
    void setTextWrap(bool) {}
    void setTextSize(int v) { size=v; }
    void setCursor(int a,int b) { x=a;y=b; }
    void drawLine(int,int,int,int,int) {}
    void print(const char* text) {
        assert(x>=0 && y>=0 && y+size*8<=64);
        assert(x+int(std::strlen(text))*6*size<=128);
        x+=int(std::strlen(text))*6*size; lines.emplace_back(text);
    }
    void display() {}
};
int main() {
    HeaterPanel p;
    assert(p.poll(0,2,false,false)==HeaterAction::None);
    assert(p.poll(100,2,false,false)==HeaterAction::None);
    p.poll(101,0,false,false); p.poll(150,0,false,false);
    p.poll(151,2,false,false);
    assert(p.poll(190,2,false,false)==HeaterAction::None);
    assert(p.poll(191,2,false,false)==HeaterAction::Enable);
    assert(p.poll(2000,2,false,false)==HeaterAction::None);
    assert(p.poll(2010,2,true,false)==HeaterAction::Stop);
    p.poll(2020,0,false,true); p.poll(2070,0,false,true);
    p.poll(2100,2,false,true); p.poll(2140,2,false,true);
    assert(p.poll(3639,2,false,true)==HeaterAction::None);
    assert(p.poll(3640,2,false,true)==HeaterAction::Acknowledge);
    assert(p.poll(3700,2,false,false)==HeaterAction::None);
    p.poll(3800,0,false,false); p.poll(3850,0,false,false);
    p.poll(3900,3,false,false); p.poll(3950,3,false,false);
    p.poll(4000,2,false,false);
    assert(p.poll(4050,2,false,false)==HeaterAction::None);
    p.poll(4100,0,false,false); p.poll(4150,0,false,false);
    p.poll(4200,1,false,true); p.poll(4250,1,false,true);
    assert(p.page==HeaterPage::Identity);
    p.poll(4300,0,false,true); p.poll(4350,0,false,true);
    p.poll(4400,4,false,true); p.poll(4450,4,false,true);
    assert(p.page==HeaterPage::Target);
    p.poll(14550,0,false,true); assert(p.page==HeaterPage::Live);
    p.inhibitHeatUntilRelease(); p.poll(14600,2,false,false);
    assert(p.poll(14650,2,false,false)==HeaterAction::None);
    Display d;
    for (auto page : {HeaterPage::Live,HeaterPage::Identity,HeaterPage::Target}) {
        HeaterView v; v.page=page; v.temperature="-20.0"; v.target="50.00 C";
        v.deviceId="HTR-ABC123DEF456"; v.ip="255.255.255.255"; v.version="3.1.0-dev"; v.state="READY";
        v.alarm="SENSOR: HEAT OFF"; v.fault=true;
        drawHeater(d,v); assert(d.lines.back()=="HEAT OFF");
        v.alarm=""; v.fault=false; drawHeater(d,v);
        if (page==HeaterPage::Target) {
            v.targetSaved=false; drawHeater(d,v);
            assert(d.lines.back()=="DEFAULT SETPOINT");
        }
    }
    std::puts("HEATER_PANEL_TESTS_OK");
}
