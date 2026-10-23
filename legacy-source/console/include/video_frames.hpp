#pragma once
#include "libretro_min.hpp"
#include <array>
#include <atomic>
#include <cstring>
#include <memory>
#include <vector>

struct VideoFrame {
  unsigned width=0,height=0;
  std::vector<uint32_t> pixels;
};

// Single emulation producer, independent presentation/capture readers. A reader
// holds an immutable frame, never a mutex needed by retro_run. Three recyclable
// buffers cover producer + displayed frame + published frame in the usual case.
class VideoFrames {
public:
  using Snapshot=std::shared_ptr<const VideoFrame>;
  Snapshot snapshot() const{return latest_.load(std::memory_order_acquire);}
  uint64_t generation() const{return generation_.load(std::memory_order_acquire);}
  bool publish(const void* data,unsigned width,unsigned height,size_t pitch,retro_pixel_format format){
    if(!data||reinterpret_cast<uintptr_t>(data)==~uintptr_t{0}||!width||!height||width>16384||height>16384)return false;
    const size_t bytes=format==RETRO_PIXEL_FORMAT_XRGB8888?4:2;
    if(format!=RETRO_PIXEL_FORMAT_XRGB8888&&format!=RETRO_PIXEL_FORMAT_RGB565&&format!=RETRO_PIXEL_FORMAT_0RGB1555)return false;
    const size_t count=static_cast<size_t>(width)*height;
    if(count>32u*1024u*1024u||pitch<static_cast<size_t>(width)*bytes||pitch>SIZE_MAX/height)return false;
    std::shared_ptr<VideoFrame> next;
    for(auto& buffer:pool_)if(!buffer||buffer.use_count()==1){if(!buffer)buffer=std::make_shared<VideoFrame>();next=buffer;break;}
    // A slow screenshot can retain old frames. Do not block or mutate them.
    if(!next)next=std::make_shared<VideoFrame>();
    next->width=width;next->height=height;next->pixels.resize(count);
    for(unsigned y=0;y<height;++y){
      const auto* source=static_cast<const unsigned char*>(data)+static_cast<size_t>(y)*pitch;
      auto* destination=next->pixels.data()+static_cast<size_t>(y)*width;
      for(unsigned x=0;x<width;++x){
        if(bytes==4){uint32_t pixel;std::memcpy(&pixel,source+static_cast<size_t>(x)*4,4);destination[x]=pixel&0x00FFFFFFu;}
        else{uint16_t pixel;std::memcpy(&pixel,source+static_cast<size_t>(x)*2,2);const unsigned red=format==RETRO_PIXEL_FORMAT_RGB565?(pixel>>11)&31:(pixel>>10)&31;const unsigned green=format==RETRO_PIXEL_FORMAT_RGB565?(pixel>>5)&63:(pixel>>5)&31;const unsigned blue=pixel&31;const unsigned g8=format==RETRO_PIXEL_FORMAT_RGB565?(green<<2)|(green>>4):(green<<3)|(green>>2);destination[x]=(((red<<3)|(red>>2))<<16)|(g8<<8)|((blue<<3)|(blue>>2));}
      }
    }
    latest_.store(std::move(next),std::memory_order_release);generation_.fetch_add(1,std::memory_order_release);return true;
  }
  // Call only after the emulation producer has stopped; readers may outlive it.
  void reset(){latest_.store({},std::memory_order_release);for(auto& buffer:pool_)buffer.reset();generation_.store(0,std::memory_order_release);}
private:
  std::array<std::shared_ptr<VideoFrame>,3> pool_{};
  std::atomic<Snapshot> latest_{};
  std::atomic<uint64_t> generation_{0};
};
