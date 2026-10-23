#include "input_bindings.hpp"
#include "audio_gain.hpp"
#include "audio_waveout.hpp"
#include <iostream>
#include <stdexcept>

void require(bool ok,const char* label){if(!ok)throw std::runtime_error(label);}
int main(){try{
  const std::array<bool,4> available{true,true,true,false};
  require(tm3input::controllerSlots(-1,-1,available)==std::array<int,2>{0,1},"two automatic controllers are distinct");
  require(tm3input::controllerSlots(-1,0,available)==std::array<int,2>{1,0},"explicit second controller reserved before automatic first");
  require(tm3input::controllerSlots(1,1,available)==std::array<int,2>{1,-1},"same controller cannot control two local players");
  require(tm3input::controllerSlots(-2,-1,available)==std::array<int,2>{-1,0},"keyboard first player leaves gamepad free for second");
  require(tm3input::controllerSlots(3,-1,available)==std::array<int,2>{-1,0},"missing explicit controller does not steal another");
  require(tm3input::controllerSlots(-1,-1,{true,false,false,false})==std::array<int,2>{0,-1},"one gamepad is not mirrored across ports");
  constexpr WORD digital[]={XINPUT_GAMEPAD_A,XINPUT_GAMEPAD_B,XINPUT_GAMEPAD_X,XINPUT_GAMEPAD_Y,XINPUT_GAMEPAD_BACK,XINPUT_GAMEPAD_START,XINPUT_GAMEPAD_DPAD_UP,XINPUT_GAMEPAD_DPAD_DOWN,XINPUT_GAMEPAD_DPAD_LEFT,XINPUT_GAMEPAD_DPAD_RIGHT,XINPUT_GAMEPAD_LEFT_SHOULDER,XINPUT_GAMEPAD_RIGHT_SHOULDER};
  for(unsigned id=0;id<12;++id){XINPUT_GAMEPAD p{};p.wButtons=digital[id];require(tm3input::padMask(p)==(1u<<(id+1)),"digital button");}
  XINPUT_GAMEPAD p{};p.bLeftTrigger=31;p.bRightTrigger=31;p.wButtons=XINPUT_GAMEPAD_LEFT_THUMB|XINPUT_GAMEPAD_RIGHT_THUMB;require(tm3input::padMask(p)==((1u<<13)|(1u<<14)|(1u<<15)|(1u<<16)),"triggers and stick clicks");
  p={};p.bLeftTrigger=30;p.sThumbLX=7849;p.sThumbRX=8689;require(tm3input::padMask(p)==0,"deadzone and trigger threshold");
  constexpr unsigned positive[]={17,20,21,24},negative[]={18,19,22,23};
  for(int axis=0;axis<4;++axis){p={};SHORT* target[]={&p.sThumbLY,&p.sThumbLX,&p.sThumbRY,&p.sThumbRX};*target[axis]=32767;require(tm3input::padMask(p)==(1u<<positive[axis]),"positive analog direction");*target[axis]=-32768;require(tm3input::padMask(p)==(1u<<negative[axis]),"negative analog direction");}
  std::array<int,16> keys{},pads{};
  for(int key:{VK_SPACE,VK_UP,VK_TAB,VK_RETURN,VK_LSHIFT,VK_RCONTROL,VK_F5,VK_NUMPAD7,VK_OEM_1,VK_DELETE}){keys[0]=key;const auto pressed=tm3input::sample(true,false,keys,pads,0,[&](int code){return code==key;});require(pressed[0]==1,"special keyboard key");require(!tm3input::keyName(key).empty(),"key label");}
  for(int slot=0;slot<16;++slot){keys={};pads={};pads[slot]=24;const auto pressed=tm3input::sample(true,true,keys,pads,1u<<24,[](int){return false;});for(int i=0;i<16;++i)require(pressed[i]==(i==slot),"custom binding all sixteen slots");}
  keys={};keys[0]=VK_SPACE;pads=tm3input::pads;auto sample=tm3input::sample(true,true,keys,pads,(1u<<13)|(1u<<14),[](int key){return key==VK_SPACE;});require(sample[0]&&sample[12]&&sample[13],"keyboard + triggers merge");
  unsigned polls=0;sample=tm3input::sample(false,true,keys,pads,~0u,[&](int){++polls;return true;});for(auto value:sample)require(!value,"focus suppression");require(!polls,"no background keyboard polling");
  sample=tm3input::sample(true,false,keys,pads,~0u,[](int){return false;});for(auto value:sample)require(!value,"controller toggle");
  const int16_t source[]={-32768,-20000,-1000,0,1000,20000,32767};int16_t destination[7]{};
  tm3audio::scale(destination,source,7,100,false);for(int i=0;i<7;++i)require(destination[i]==source[i],"100 percent audio passthrough");
  tm3audio::scale(destination,source,7,200,true);for(auto value:destination)require(value==0,"mute");
  tm3audio::scale(destination,source,7,50,false);for(int i=0;i<7;++i)require(destination[i]==source[i]/2,"50 percent gain");
  tm3audio::scale(destination,source,7,200,false);require(destination[0]==-32768&&destination[1]==-32768&&destination[5]==32767&&destination[6]==32767,"200 percent clipping");
  tm3audio::scale(destination,source,7,0,false);for(auto value:destination)require(value==0,"zero volume");
  require(tm3input::virtualKey(VK_CONTROL,1u<<24)==VK_RCONTROL&&tm3input::virtualKey(VK_CONTROL,0)==VK_LCONTROL,"left/right control");
  if(waveOutGetNumDevs()){
    AudioWaveOut output;output.setMuted(true);require(output.open(44100),"open default output");std::array<int16_t,16384> silence{};output.push(silence.data(),128);output.setDevice(0);output.push(silence.data(),128);output.setDevice(-1);output.push(silence.data(),128);output.setDevice(99999);output.push(silence.data(),128);require(output.droppedFrames()==0,"audio device switch/fallback");
    for(int latency:{20,40,80}){output.setLatency(latency);output.push(silence.data(),128);require(output.droppedFrames()==0,"latency change");}
    output.push(silence.data(),8192);require(output.droppedFrames()>0,"bounded buffer drops excess without blocking");output.close();require(output.open(44100),"reopen after close");
    // 80 ms capacity -> 8 * 441 stereo frames; start only after 4 blocks.
    require(output.buffering(),"new device waits for reserve");
    output.push(silence.data(),441*3);Sleep(100);
    require(output.buffering()&&output.underruns()==0,"partial reserve stays paused without draining");
    output.push(silence.data(),441);require(!output.buffering(),"four blocks start playback");
    Sleep(200);output.push(silence.data(),441);
    require(output.buffering()&&output.underruns()==1,"drained device rebuilds reserve");
    Sleep(100);output.push(silence.data(),441);
    require(output.buffering()&&output.underruns()==1,"refill does not count repeated underruns");
    output.push(silence.data(),441*2);require(!output.buffering(),"refill restarts playback");
    output.close();require(output.buffering(),"close resets playback state");
    std::cout<<"PASS: silent output, device fallback, latency settings, nonblocking overflow, reserve start, underrun refill and reopen.\n";
  }else std::cout<<"SKIP: no physical audio output available.\n";
  std::cout<<"PASS: 24 controller inputs, sixteen remappable buttons, special keys, deadzones, focus gate, keyboard/controller merge and audio gain/mute/clipping.\n";return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<"\n";return 1;}}
