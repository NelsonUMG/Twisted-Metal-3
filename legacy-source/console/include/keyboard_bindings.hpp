#pragma once
#include "libretro_min.hpp"
#include <array>
#include <cstdint>

namespace tm3keyboard {
// Libretro order, NOT PlayStation bit order: B=cross, Y=square,
// A=circle, X=triangle. Blank controls in the user's screenshot stay unbound.
inline constexpr std::array<int,16> keys{
  'F', 'C', 0, 'V', 'W', 'S', 'A', 'D', 'J', 'T', 'H', 0, 'G', 'Y', 0, 0
};
// Independent keyboard defaults for PS1 controller port 2 (Windows VK values).
inline constexpr std::array<int,16> keys2{
  0x61,0x64,0x60,0x0D,0x26,0x28,0x25,0x27,0x63,0x65,0x67,0x69,0x68,0x6B,0,0
};
template<class KeyDown>
std::array<int16_t,16> sample(bool enabled, KeyDown keyDown) {
  std::array<int16_t,16> buttons{};
  if(enabled) for(unsigned id=0;id<keys.size();++id)
    if(keys[id]) buttons[id]=keyDown(keys[id])?1:0;
  return buttons;
}
}
