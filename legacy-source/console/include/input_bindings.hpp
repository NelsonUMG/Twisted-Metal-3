#pragma once
#include "keyboard_bindings.hpp"
#include <windows.h>
#include <Xinput.h>
#include <algorithm>
#include <string>

namespace tm3input {
// Stable, persisted IDs. Analog directions are mapped to the game's digital buttons.
inline constexpr std::array<int,16> pads{1,3,5,6,7,8,9,10,2,4,11,12,13,14,15,16};
inline constexpr const wchar_t* padNames[]={L"Sin asignar",L"A",L"B",L"X",L"Y",L"Back",L"Start",L"Cruceta ↑",L"Cruceta ↓",L"Cruceta ←",L"Cruceta →",L"LB",L"RB",L"LT",L"RT",L"LS pulsar",L"RS pulsar",L"LS ↑",L"LS ↓",L"LS ←",L"LS →",L"RS ↑",L"RS ↓",L"RS ←",L"RS →"};
inline uint32_t padMask(const XINPUT_GAMEPAD& pad){
  constexpr WORD buttons[]={XINPUT_GAMEPAD_A,XINPUT_GAMEPAD_B,XINPUT_GAMEPAD_X,XINPUT_GAMEPAD_Y,XINPUT_GAMEPAD_BACK,XINPUT_GAMEPAD_START,XINPUT_GAMEPAD_DPAD_UP,XINPUT_GAMEPAD_DPAD_DOWN,XINPUT_GAMEPAD_DPAD_LEFT,XINPUT_GAMEPAD_DPAD_RIGHT,XINPUT_GAMEPAD_LEFT_SHOULDER,XINPUT_GAMEPAD_RIGHT_SHOULDER};
  uint32_t mask=0;for(unsigned i=0;i<12;++i)if(pad.wButtons&buttons[i])mask|=1u<<(i+1);
  if(pad.bLeftTrigger>XINPUT_GAMEPAD_TRIGGER_THRESHOLD)mask|=1u<<13;
  if(pad.bRightTrigger>XINPUT_GAMEPAD_TRIGGER_THRESHOLD)mask|=1u<<14;
  if(pad.wButtons&XINPUT_GAMEPAD_LEFT_THUMB)mask|=1u<<15;
  if(pad.wButtons&XINPUT_GAMEPAD_RIGHT_THUMB)mask|=1u<<16;
  const SHORT axes[]={pad.sThumbLY,pad.sThumbLX,pad.sThumbRY,pad.sThumbRX};
  constexpr int positive[]={17,20,21,24},negative[]={18,19,22,23};
  for(int i=0;i<4;++i){const int threshold=i<2?XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE:XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE;if(axes[i]>threshold)mask|=1u<<positive[i];if(axes[i]<-threshold)mask|=1u<<negative[i];}
  return mask;
}
struct PadSnapshot {bool connected=false;uint32_t mask=0;int slot=-1;};
inline PadSnapshot readPad(int selected){XINPUT_STATE state{};for(DWORD slot=0;slot<4;++slot)if((selected<0||slot==static_cast<DWORD>(selected))&&XInputGetState(slot,&state)==ERROR_SUCCESS)return {true,padMask(state.Gamepad),static_cast<int>(slot)};return {};}
// -2 disables a player; -1 auto-selects. A physical controller is never shared.
inline std::array<int,2> controllerSlots(int first,int second,const std::array<bool,4>& connected){
  std::array<int,2> result{-1,-1};
  if(first>=0&&first<4&&connected[first])result[0]=first;
  if(second>=0&&second<4&&connected[second]&&second!=result[0])result[1]=second;
  if(first==-1)for(int slot=0;slot<4;++slot)if(connected[slot]&&slot!=result[1]){result[0]=slot;break;}
  if(second==-1)for(int slot=0;slot<4;++slot)if(connected[slot]&&slot!=result[0]){result[1]=slot;break;}
  return result;
}
inline std::array<PadSnapshot,2> readPair(int first,int second){
  if(second==-2)return {first==-2?PadSnapshot{}:readPad(first),PadSnapshot{}};
  if(first==-2)return {PadSnapshot{},readPad(second)};
  std::array<PadSnapshot,4> snapshots{};std::array<bool,4> connected{};
  for(int slot=0;slot<4;++slot){XINPUT_STATE state{};if(XInputGetState(slot,&state)==ERROR_SUCCESS){connected[slot]=true;snapshots[slot]={true,padMask(state.Gamepad),slot};}}
  const auto slots=controllerSlots(first,second,connected);std::array<PadSnapshot,2> result{};
  for(int port=0;port<2;++port)if(slots[port]>=0)result[port]=snapshots[slots[port]];
  return result;
}
template<class KeyDown> std::array<int16_t,16> sample(bool enabled,bool controller,const std::array<int,16>& keys,const std::array<int,16>& bindings,uint32_t pad,KeyDown down){
  std::array<int16_t,16> result{};if(!enabled)return result;
  for(unsigned i=0;i<16;++i)result[i]=(keys[i]>0&&keys[i]<256&&down(keys[i]))||(controller&&bindings[i]>0&&bindings[i]<=24&&(pad&(1u<<bindings[i])));
  return result;
}
inline std::wstring keyName(int key){
  if(!key)return L"Sin asignar";
  UINT scan=MapVirtualKeyW(key,MAPVK_VK_TO_VSC);if(key==VK_LEFT||key==VK_RIGHT||key==VK_UP||key==VK_DOWN||key==VK_INSERT||key==VK_DELETE||key==VK_HOME||key==VK_END||key==VK_PRIOR||key==VK_NEXT||key==VK_DIVIDE||key==VK_NUMLOCK||key==VK_RCONTROL||key==VK_RMENU)scan|=0x100;
  wchar_t name[96]{};if(GetKeyNameTextW(static_cast<LONG>(scan<<16),name,96))return name;
  return L"Tecla "+std::to_wstring(key);
}
inline int virtualKey(WPARAM value,LPARAM details){
  int key=static_cast<int>(value);const bool extended=(details&(1u<<24))!=0;
  if(key==VK_CONTROL)return extended?VK_RCONTROL:VK_LCONTROL;
  if(key==VK_MENU)return extended?VK_RMENU:VK_LMENU;
  if(key==VK_SHIFT){const auto side=MapVirtualKeyW((details>>16)&255,MAPVK_VSC_TO_VK_EX);return side?static_cast<int>(side):VK_SHIFT;}
  return key;
}
}
