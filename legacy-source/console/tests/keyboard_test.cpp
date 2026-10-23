#include "keyboard_bindings.hpp"
#include <iostream>
#include <stdexcept>

void require(bool ok){if(!ok)throw std::runtime_error("keyboard test failed");}
int main(){
  const std::array<int,16> expected{'F','C',0,'V','W','S','A','D','J','T','H',0,'G','Y',0,0};
  require(tm3keyboard::keys==expected);
  for(unsigned id=0;id<16;++id){
    const auto buttons=tm3keyboard::sample(true,[&](int key){return key==expected[id];});
    for(unsigned other=0;other<16;++other)
      require(buttons[other]==(expected[id]!=0 && other==id ? 1:0));
  }
  unsigned polls=0;
  const auto inactive=tm3keyboard::sample(false,[&](int){++polls;return true;});
  require(polls==0);
  for(auto button:inactive)require(button==0);
  const auto released=tm3keyboard::sample(true,[](int){return false;});
  for(auto button:released)require(button==0);
  const auto chord=tm3keyboard::sample(true,[](int key){return key=='W'||key=='F'||key=='V';});
  unsigned mask=0;
  for(unsigned id=0;id<16;++id)if(chord[id])mask|=1u<<id;
  require(mask==((1u<<RETRO_DEVICE_ID_JOYPAD_UP)|(1u<<RETRO_DEVICE_ID_JOYPAD_B)|(1u<<RETRO_DEVICE_ID_JOYPAD_START)));
  require(tm3keyboard::keys[RETRO_DEVICE_ID_JOYPAD_START]=='V');
  require(tm3keyboard::keys[RETRO_DEVICE_ID_JOYPAD_R]==0);
  require(tm3keyboard::keys[RETRO_DEVICE_ID_JOYPAD_SELECT]==0);
  std::cout<<"Keyboard screenshot mapping, all 16 slots, chords, release and focus gate: PASS\n";
}
