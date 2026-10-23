#include "video_frames.hpp"
#include "thread_schedule.hpp"
#include <condition_variable>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>

void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
uint32_t reference(uint16_t value,bool rgb565){const unsigned r=rgb565?(value>>11)&31:(value>>10)&31,g=rgb565?(value>>5)&63:(value>>5)&31,b=value&31;return (((r<<3)|(r>>2))<<16)|((rgb565?(g<<2)|(g>>4):(g<<3)|(g>>2))<<8)|((b<<3)|(b>>2));}
int main(int argc,char** argv){try{
  VideoFrames frames;
  require(!frames.snapshot(),"initial frame empty");
  std::vector<uint16_t> source(65536);for(unsigned i=0;i<source.size();++i)source[i]=static_cast<uint16_t>(i);
  for(auto format:{RETRO_PIXEL_FORMAT_0RGB1555,RETRO_PIXEL_FORMAT_RGB565}){require(frames.publish(source.data(),256,256,512,format),"16-bit publish");const auto image=frames.snapshot();for(unsigned i=0;i<source.size();++i)require(image->pixels[i]==reference(source[i],format==RETRO_PIXEL_FORMAT_RGB565),"exhaustive 16-bit color equivalence");}
  const uint32_t pitched[]={0xFF123456,0xABABCDEF,0xDEADBEEF,0xFF010203,0xFFFAFBFC,0xDEADBEEF};
  require(frames.publish(pitched,2,2,12,RETRO_PIXEL_FORMAT_XRGB8888),"pitched XRGB publish");auto retained=frames.snapshot();require(retained->pixels==std::vector<uint32_t>{0x123456,0xABCDEF,0x010203,0xFAFBFC},"pitch and alpha correctness");
  const auto generation=frames.generation();require(!frames.publish(nullptr,2,2,12,RETRO_PIXEL_FORMAT_XRGB8888),"null rejected");require(!frames.publish(reinterpret_cast<void*>(~uintptr_t{0}),2,2,12,RETRO_PIXEL_FORMAT_XRGB8888),"hardware sentinel rejected");require(!frames.publish(pitched,2,2,4,RETRO_PIXEL_FORMAT_XRGB8888),"short pitch rejected");require(!frames.publish(pitched,0,2,12,RETRO_PIXEL_FORMAT_XRGB8888),"zero width rejected");require(frames.generation()==generation,"invalid input preserves frame");
  // The consumer retains frames for the entire producer run. A GDI draw or
  // screenshot doing the same must not stall the producer or see overwritten data.
  std::array<VideoFrames::Snapshot,4> held;
  for(unsigned i=0;i<held.size();++i){const uint32_t pixel=i+1;frames.publish(&pixel,1,1,4,RETRO_PIXEL_FORMAT_XRGB8888);held[i]=frames.snapshot();}
  std::atomic<bool> done=false,valid=true;
  std::jthread producer([&]{std::vector<uint32_t> pixels(64*64);for(unsigned step=1;step<=1500;++step){std::fill(pixels.begin(),pixels.end(),step);if(!frames.publish(pixels.data(),64,64,64*4,RETRO_PIXEL_FORMAT_XRGB8888))valid=false;}done.store(true,std::memory_order_release);});
  unsigned reads=0;while(!done.load(std::memory_order_acquire)){auto frame=frames.snapshot();if(frame&&frame->pixels.size()==4096){for(auto pixel:frame->pixels)if(pixel!=frame->pixels.front())valid=false;++reads;}std::this_thread::yield();}producer.join();require(valid,"no torn concurrent frames");for(unsigned i=0;i<held.size();++i)require(held[i]->pixels[0]==i+1,"retained frame not overwritten");require(retained->pixels[0]==0x123456,"old screenshot remains immutable");
  const auto synthetic=tm3threads::representatives({{0,3},{0,12},{0,48},{1,3}},0,0b101010);require(synthetic.size()==3&&synthetic[0].Number==1&&synthetic[1].Number==3&&synthetic[2].Number==5,"physical cores respect affinity and SMT masks");
  DWORD_PTR affinityBefore=0,systemMask=0,affinityAfter=0;GetProcessAffinityMask(GetCurrentProcess(),&affinityBefore,&systemMask);const auto priority=GetPriorityClass(GetCurrentProcess());
  GROUP_AFFINITY groupBefore{},groupAfter{};GetThreadGroupAffinity(GetCurrentThread(),&groupBefore);PROCESSOR_NUMBER before{},after{};GetThreadIdealProcessorEx(GetCurrentThread(),&before);
  PROCESSOR_NUMBER preferred{};bool multimedia=false,ideal=false;
  {tm3threads::Schedule schedule(tm3threads::Role::Emulation,2);preferred=schedule.ideal();ideal=schedule.idealApplied();multimedia=schedule.multimediaApplied();GetThreadGroupAffinity(GetCurrentThread(),&groupAfter);require(groupBefore.Mask==groupAfter.Mask&&groupBefore.Group==groupAfter.Group,"thread affinity unchanged");}
  GetThreadIdealProcessorEx(GetCurrentThread(),&after);GetProcessAffinityMask(GetCurrentProcess(),&affinityAfter,&systemMask);require(affinityBefore==affinityAfter&&priority==GetPriorityClass(GetCurrentProcess()),"process priority and affinity unchanged");require(before.Group==after.Group&&before.Number==after.Number,"ideal hint restored");
  const auto cores=tm3threads::topology();const auto representatives=tm3threads::representatives(cores,groupBefore.Group,groupBefore.Mask);
  if(tm3threads::enabled()&&!representatives.empty()&&GetActiveProcessorGroupCount()==1)require(ideal,"ideal processor applied on supported topology");
  std::cout<<"PASS: exhaustive RGB565/1555, pitched XRGB, immutable retained frames, "<<reads<<" concurrent reads, "<<representatives.size()<<" physical cores, "<<GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)<<" logical CPUs, affinity unchanged; MMCSS="<<multimedia<<" ideal="<<ideal<<".\n";
  if(argc>1){std::ofstream report(argv[1]);report<<"{\n  \"passed\": true,\n  \"physical_cores_available\": "<<representatives.size()<<",\n  \"logical_cpus\": "<<GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)<<",\n  \"process_affinity_unchanged\": true,\n  \"ideal_applied\": "<<(ideal?"true":"false")<<",\n  \"preferred_processor\": "<<static_cast<unsigned>(preferred.Number)<<",\n  \"mmcss_games_registered\": "<<(multimedia?"true":"false")<<",\n  \"concurrent_frames_not_torn\": true\n}\n";require(report.good(),"write QA report");}
  frames.reset();require(!frames.snapshot()&&retained->pixels[0]==0x123456,"reset preserves retained reader");return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<"\n";return 1;}}
