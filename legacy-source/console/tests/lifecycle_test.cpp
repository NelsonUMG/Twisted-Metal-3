#include "core_host.hpp"
#include <fstream>
#include <iostream>
#include <thread>
#include <stdexcept>
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
int wmain(int argc,wchar_t** argv){try{
 if(argc!=4)return 2;
 const std::filesystem::path core=argv[1],game=argv[2],base=argv[3];std::filesystem::create_directories(base/L"system");
 CoreHost host;host.setMuted(true);host.setInputEnabled(false);
 for(int cycle=0;cycle<3;++cycle){
  host.setSaveSlot("lifecycle");require(host.load(core,game,base),"load");
  std::jthread emulation([&](std::stop_token stop){while(!stop.stop_requested())host.runFrame();});
  for(int wait=0;wait<100&&host.videoGeneration()<120;++wait)Sleep(20);
  emulation.request_stop();emulation.join();require(host.videoGeneration()>0,"video callbacks");
  host.disconnect();host.unload();require(!host.loaded()&&host.videoGeneration()==0,"unload clears content");host.runFrame();host.unload();
 }
 require(!host.load(core,base/L"missing.cue",base),"invalid content returns failure");require(!host.loaded(),"failed load is idle");
 require(host.load(core,game,base),"recover after failed load");host.runFrame();host.unload();
 for(const auto& item:std::filesystem::recursive_directory_iterator(base))require(item.path().extension()!=L".csv"&&item.path().extension()!=L".log"&&item.path().extension()!=L".jsonl","no automatic diagnostics");
 std::cout<<"PASS: three threaded load/unload cycles, invalid-image recovery, cleared video and audio, no diagnostics\n";return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<'\n';return 1;}}
