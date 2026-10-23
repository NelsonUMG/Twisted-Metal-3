#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
namespace tm3audio {
inline void scale(int16_t* destination,const int16_t* source,size_t samples,int volume,bool muted){
  const int gain=muted?0:std::clamp(volume,0,200);
  if(gain==100){std::memcpy(destination,source,samples*sizeof(int16_t));return;}
  for(size_t i=0;i<samples;++i)destination[i]=static_cast<int16_t>(std::clamp((static_cast<int>(source[i])*gain)/100,-32768,32767));
}
}
