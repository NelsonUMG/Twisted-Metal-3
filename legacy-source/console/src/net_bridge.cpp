#include "net_bridge.hpp"
#include "thread_schedule.hpp"
#include "diagnostics_mode.hpp"
#include <ws2tcpip.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <cwctype>
#include <filesystem>
#include <iomanip>
#include <random>
#include <sstream>
#include <string_view>

namespace {
bool boundaryEnabled(){
  static const bool enabled=[](){wchar_t value[8]{};return GetEnvironmentVariableW(L"TM3O_LINK_BOUNDARY",value,8)>0 && value[0]==L'1';}();
  return enabled;
}
uint64_t boundaryQpc(){LARGE_INTEGER q{};QueryPerformanceCounter(&q);return static_cast<uint64_t>(q.QuadPart);}
bool initWsa(){
  static const bool initialized=[](){WSADATA data{};return WSAStartup(MAKEWORD(2,2),&data)==0;}();
  return initialized;
}

bool tcpPeerClosed(SOCKET socket){
  fd_set readable;
  FD_ZERO(&readable);
  FD_SET(socket,&readable);
  timeval timeout{};
  const int ready=select(0,&readable,nullptr,nullptr,&timeout);
  if(ready==SOCKET_ERROR)return true;
  if(ready==0)return false;
  char byte=0;
  const int peeked=recv(socket,&byte,1,MSG_PEEK);
  if(peeked==0)return true;
  if(peeked==SOCKET_ERROR)return WSAGetLastError()!=WSAEWOULDBLOCK;
  return false;
}

bool sequenceBefore(uint32_t lhs,uint32_t rhs){
  return static_cast<int32_t>(lhs-rhs)<0;
}

uint32_t firstWord(const uint8_t* data,size_t size){
  uint32_t value=0;
  if(size==0)return value;
  std::memcpy(&value,data,std::min<size_t>(size,sizeof(value)));
  return value;
}

constexpr uint32_t kGameplayBatchReturn=0x8003AA98u;
constexpr size_t kRngDiagBase=0xF00000;
constexpr size_t kRngCounterOffset=kRngDiagBase+0x10;
constexpr size_t kRngMagicOffset=kRngDiagBase+0x14;
constexpr size_t kRngVersionOffset=kRngDiagBase+0x18;
constexpr size_t kRngEntriesOffset=kRngDiagBase+0x20;
constexpr size_t kRngEntrySize=16;
constexpr uint32_t kRngEntryCount=4096;
constexpr uint32_t kRngEntryMask=kRngEntryCount-1;
constexpr size_t kRngRingEnd=kRngEntriesOffset+kRngEntryCount*kRngEntrySize;
constexpr size_t kRngCodecaveOffset=0xF10100;
constexpr uint32_t kRngDiagMagic=0x31474E52u; // bytes: RNG1
constexpr uint32_t kRngDiagVersion=1;
constexpr std::array<uint32_t,15> kRngCodecaveWords{
  0x8F820708u, // lw    v0,0x708(gp)
  0x3C0880F0u, // lui   t0,0x80F0
  0x8D090010u, // lw    t1,0x10(t0)
  0x00000000u, // nop: load delay
  0x312A0FFFu, // andi  t2,t1,0x0FFF
  0x000A5100u, // sll   t2,t2,4
  0x250B0020u, // addiu t3,t0,0x20
  0x016A5821u, // addu  t3,t3,t2
  0xAD7F0000u, // sw    ra,0(t3)
  0xAD620004u, // sw    v0,4(t3)
  0x25290001u, // addiu t1,t1,1
  0xAD090010u, // sw    t1,0x10(t0)
  0x3C0341C6u, // lui   v1,0x41C6 (instruccion original)
  0x0800E83Eu, // j     0x8003A0F8
  0x00000000u, // nop
};
static_assert(kRngCodecaveWords.size()*sizeof(uint32_t)==60);

constexpr size_t kAiProfileBase=0xC00000;
constexpr size_t kAiProfileEventsOffset=0xC00100;
constexpr size_t kAiProfileEventSize=0xF0;
constexpr uint32_t kAiProfileEventCount=4096;
constexpr uint32_t kAiProfileEventMask=kAiProfileEventCount-1;
constexpr size_t kAiProfileHistogramOffset=0xD00000;
constexpr uint32_t kAiProfileHistogramPcBegin=0x80010000u;
constexpr uint32_t kAiProfileHistogramPcEnd=0x80070000u;
constexpr uint32_t kAiProfileHistogramCategories=4;
constexpr size_t kAiProfileHistogramBytes=
  static_cast<size_t>(kAiProfileHistogramPcEnd-kAiProfileHistogramPcBegin)/4*
  sizeof(uint32_t)*kAiProfileHistogramCategories;
constexpr size_t kAiProfileEnd=kAiProfileHistogramOffset+kAiProfileHistogramBytes;
constexpr uint32_t kAiProfileMagic=0x33504941u; // bytes: AIP3
constexpr uint32_t kAiProfileVersion=3;
static_assert(kAiProfileEventsOffset+static_cast<size_t>(kAiProfileEventCount)*
              kAiProfileEventSize<=kAiProfileHistogramOffset);
static_assert(kAiProfileEnd<=kRngDiagBase);

const char* aiProfileTargetName(uint32_t target){
  switch(target){
    case 1:return "boundary";
    case 2:return "world_update";
    case 3:return "world_collision";
    case 4:return "object_update";
    case 5:return "vehicle_update";
    case 6:return "control_dispatch";
    case 7:return "cpu_callback";
    case 8:return "ai_decisions";
    case 9:return "ai_proximity_scan";
    case 10:return "path_wrapper";
    case 11:return "path_search";
    case 12:return "post_control";
    case 13:return "effects";
    default:return "unknown";
  }
}

uint32_t readU32(const uint8_t* source){
  uint32_t value=0;
  std::memcpy(&value,source,sizeof(value));
  return value;
}

void writeU32(uint8_t* destination,uint32_t value){
  std::memcpy(destination,&value,sizeof(value));
}

bool installRngCallerInstrumentation(uint8_t* ram,size_t ramSize){
  constexpr size_t caveBytes=kRngCodecaveWords.size()*sizeof(uint32_t);
  if(!ram||ramSize<kRngCodecaveOffset+caveBytes)return false;
  if(readU32(ram+kRngMagicOffset)!=kRngDiagMagic||
     readU32(ram+kRngVersionOffset)!=kRngDiagVersion){
    std::fill(ram+kRngCounterOffset,ram+kRngRingEnd,uint8_t{0});
    writeU32(ram+kRngMagicOffset,kRngDiagMagic);
    writeU32(ram+kRngVersionOffset,kRngDiagVersion);
  }
  if(std::memcmp(ram+kRngCodecaveOffset,kRngCodecaveWords.data(),caveBytes)!=0){
    std::memcpy(ram+kRngCodecaveOffset,kRngCodecaveWords.data(),caveBytes);
  }
  return true;
}

std::filesystem::path executableDirectory(){
  std::array<wchar_t,32768> modulePath{};
  const DWORD length=GetModuleFileNameW(
    nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  if(length==0)return {};
  return std::filesystem::path(std::wstring(modulePath.data(),length)).parent_path();
}

bool rngCoreTraceExecutable(){
  std::array<wchar_t,32768> modulePath{};
  const DWORD length=GetModuleFileNameW(
    nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  if(length==0)return false;
  return std::wstring_view(modulePath.data(),length).find(L"RNGCoreTrace")!=
    std::wstring_view::npos;
}

bool aiProfileExecutable(){
  std::array<wchar_t,32768> modulePath{};
  const DWORD length=GetModuleFileNameW(
    nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  if(length==0)return false;
  std::wstring name(modulePath.data(),length);
  std::transform(name.begin(),name.end(),name.begin(),
    [](wchar_t ch){return static_cast<wchar_t>(std::towlower(ch));});
  return name.find(L"aiprofile")!=std::wstring::npos;
}

bool aiProfileV3Executable(){
  std::array<wchar_t,32768> modulePath{};
  const DWORD length=GetModuleFileNameW(
    nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  if(length==0)return false;
  std::wstring name(modulePath.data(),length);
  std::transform(name.begin(),name.end(),name.begin(),
    [](wchar_t ch){return static_cast<wchar_t>(std::towlower(ch));});
  return name.find(L"aiprofilev3")!=std::wstring::npos;
}

enum class GameplaySyncStatus {
  Ok,
  InvalidTail,
  TimeMismatch,
  RandomMismatch,
};

struct GameplaySyncTail {
  bool valid=false;
  uint32_t vehicleCount=0;
  uint32_t time=0;
  uint32_t random=0;
};

GameplaySyncTail gameplaySyncTail(const std::vector<uint8_t>& payload){
  GameplaySyncTail result{};
  constexpr size_t kFixedBytes=12;
  constexpr size_t kVehicleBytes=24;
  if(payload.size()<kFixedBytes)return result;
  const size_t vehicleBytes=payload.size()-kFixedBytes;
  if(vehicleBytes%kVehicleBytes!=0)return result;
  const size_t vehicleCount=vehicleBytes/kVehicleBytes;
  if(vehicleCount>4)return result;
  result.valid=true;
  result.vehicleCount=static_cast<uint32_t>(vehicleCount);
  std::memcpy(&result.time,payload.data()+payload.size()-8,sizeof(result.time));
  std::memcpy(&result.random,payload.data()+payload.size()-4,sizeof(result.random));
  return result;
}

void appendGameplaySyncTail(std::ostringstream& line,const char* label,
                            const GameplaySyncTail& tail){
  if(!tail.valid){
    line<<" "<<label<<"-sync-tail=INVALID";
    return;
  }
  line<<" "<<label<<"-count="<<std::dec<<tail.vehicleCount
    <<" "<<label<<"-time=0x"<<std::hex<<std::uppercase<<tail.time
    <<" "<<label<<"-random=0x"<<tail.random;
}

GameplaySyncStatus appendGameplaySyncComparison(
                                  std::ostringstream& line,
                                  const std::vector<uint8_t>& localPayload,
                                  const std::vector<uint8_t>& peerPayload){
  const auto local=gameplaySyncTail(localPayload);
  const auto peer=gameplaySyncTail(peerPayload);
  appendGameplaySyncTail(line,"local",local);
  appendGameplaySyncTail(line,"peer",peer);
  if(!local.valid||!peer.valid){
    line<<" sync=INVALID_TAIL";
    return GameplaySyncStatus::InvalidTail;
  }else if(local.time!=peer.time){
    line<<" sync=TIME_MISMATCH";
    return GameplaySyncStatus::TimeMismatch;
  }else if(local.random!=peer.random){
    line<<" sync=RANDOM_MISMATCH";
    return GameplaySyncStatus::RandomMismatch;
  }else{
    line<<" sync=OK";
    return GameplaySyncStatus::Ok;
  }
}
}

NetBridge::~NetBridge(){
  worker_.request_stop();
  closeSockets();
  if(worker_.joinable())worker_.join();
  if(udpReadEvent_!=WSA_INVALID_EVENT)WSACloseEvent(udpReadEvent_);
  if(aiProfileCsv_)aiProfileCsv_.flush();
}

bool NetBridge::host(uint16_t port){
  if(!initWsa()||worker_.joinable())return false;
  openTrace(aiProfileV3Executable()?L"TM3Online_Oscar.aiprofilev3.net.trace.log":
            aiProfileExecutable()?L"TM3Online_Oscar.aiprofile.net.trace.log":
            rngCoreTraceExecutable()?L"TM3Online_Oscar.rngcoretrace.trace.log":
                                     L"TM3Online_Oscar.rngcaller.trace.log");
  transportHost_=true;
  localRole_.store(0,std::memory_order_release);
  setStatus("iniciando host TCP/UDP");
  worker_=std::jthread([this,port](std::stop_token stop){tm3threads::Schedule schedule(tm3threads::Role::Network,2);workerHost(port,stop);});
  return true;
}

bool NetBridge::join(const std::string& host,uint16_t port){
  if(!initWsa()||worker_.joinable())return false;
  openTrace(aiProfileV3Executable()?L"TM3Online_Sofia.aiprofilev3.net.trace.log":
            aiProfileExecutable()?L"TM3Online_Sofia.aiprofile.net.trace.log":
            rngCoreTraceExecutable()?L"TM3Online_Sofia.rngcoretrace.trace.log":
                                     L"TM3Online_Sofia.rngcaller.trace.log");
  transportHost_=false;
  localRole_.store(0,std::memory_order_release);
  setStatus("conectando por TCP");
  worker_=std::jthread([this,host,port](std::stop_token stop){tm3threads::Schedule schedule(tm3threads::Role::Network,4);workerJoin(host,port,stop);});
  return true;
}

void NetBridge::poll(uint8_t* ram,size_t ramSize){
  const bool installed=installRngCallerInstrumentation(ram,ramSize);
  const bool aiProfileInstalled=initializeAiProfile(ram,ramSize);
  if(aiProfileInstalled)drainAiProfile(ram,ramSize);
  rngInstrumentationReady_.store(installed,std::memory_order_release);
  aiProfileReady_.store(aiProfileInstalled,std::memory_order_release);
  rngCallCount_.store(installed?readU32(ram+kRngCounterOffset):0,
                      std::memory_order_release);
  ramSize_.store(ramSize,std::memory_order_release);
  ram_.store(ram,std::memory_order_release);
}

std::string NetBridge::status() const{
  std::scoped_lock lock(mutex_);
  std::ostringstream output;
  output<<status_<<" | game-role="<<localRole_.load(std::memory_order_acquire)
    <<" ram="<<(ramSize_.load(std::memory_order_acquire)/(1024*1024))<<"MiB"
    <<" role-req="<<roleRequests_.load()
    <<" req="<<requests_.load()
    <<" io="<<lastSendSize_.load()<<"/"<<lastRecvCapacity_.load()
    <<" UDP tx="<<udpSent_.load()<<" rx="<<udpReceived_.load()
    <<" ok="<<completed_.load()<<" err="<<errors_.load()<<" seq="<<lastSequence_.load()
    <<" ord="<<lastOrdinal_.load()<<">"<<lastRemoteOrdinal_.load()
    <<" retry="<<pendingRetransmissions_.load()
    <<" call="<<std::hex<<std::uppercase<<lastCallSite_.load()
    <<" word="<<lastSendWord_.load()<<">"<<lastRecvWord_.load()
    <<" rnglog="<<(rngInstrumentationReady_.load(std::memory_order_acquire)?"ON":"OFF")
    <<" rngcalls="<<std::dec<<rngCallCount_.load(std::memory_order_acquire)
    <<" dump="<<(rngDumped_.load(std::memory_order_acquire)?"YES":"NO")
    <<" aiprof="<<(aiProfileReady_.load(std::memory_order_acquire)?"ON":"OFF")
    <<" aievents="<<aiProfileEventCount_.load(std::memory_order_acquire)
    <<" aidrop="<<aiProfileDroppedEvents_.load(std::memory_order_acquire)
    <<" aihist="<<aiProfileHistogramSequence_.load(std::memory_order_acquire);
  return output.str();
}

bool NetBridge::initializeAiProfile(uint8_t* ram,size_t ramSize){
  if(!aiProfileExecutable())return false;
  if(!ram||ramSize<kAiProfileEnd)return false;
  if(aiProfileGeneration_!=0)return
    readU32(ram+kAiProfileBase)==kAiProfileMagic&&
    readU32(ram+kAiProfileBase+4)==kAiProfileVersion&&
    readU32(ram+kAiProfileBase+8)==aiProfileGeneration_;

  uint32_t generation=1;
  if(readU32(ram+kAiProfileBase)==kAiProfileMagic&&
     readU32(ram+kAiProfileBase+4)==kAiProfileVersion){
    generation=readU32(ram+kAiProfileBase+8)+1;
    if(generation==0)generation=1;
  }
  std::fill(ram+kAiProfileBase,ram+kAiProfileBase+0x100,uint8_t{0});
  writeU32(ram+kAiProfileBase+0x00,kAiProfileMagic);
  writeU32(ram+kAiProfileBase+0x04,kAiProfileVersion);
  writeU32(ram+kAiProfileBase+0x08,generation);
  writeU32(ram+kAiProfileBase+0x0C,1);
  writeU32(ram+kAiProfileBase+0x14,kAiProfileEventCount);
  writeU32(ram+kAiProfileBase+0x18,static_cast<uint32_t>(kAiProfileEventSize));
  writeU32(ram+kAiProfileBase+0x2C,static_cast<uint32_t>(kAiProfileHistogramOffset));
  writeU32(ram+kAiProfileBase+0x30,kAiProfileHistogramPcBegin);
  writeU32(ram+kAiProfileBase+0x34,kAiProfileHistogramPcEnd);

  aiProfileGeneration_=generation;
  aiProfileNextEvent_=0;
  aiProfileLastHistogramSequence_=0;
  aiProfilePolls_=0;
  aiProfileDroppedEvents_.store(0,std::memory_order_release);

  const auto directory=executableDirectory();
  if(directory.empty())return false;
  const auto csvPath=directory/(transportHost_?
    (aiProfileV3Executable()?L"TM3Online_Oscar.aiprofilev3.events.csv":
                             L"TM3Online_Oscar.aiprofile.events.csv"):
    (aiProfileV3Executable()?L"TM3Online_Sofia.aiprofilev3.events.csv":
                             L"TM3Online_Sofia.aiprofile.events.csv"));
  aiProfileCsv_.open(csvPath,std::ios::out|std::ios::trunc);
  if(!aiProfileCsv_)return false;
  aiProfileCsv_<<"event_seq,target_id,target,phase,pc,ra,sp,gp,timestamp,"
    "instruction,duration_instructions,duration_timestamp,boundary_ordinal,"
    "vehicle_order,vehicle,table_index,f50,driver_type,callback,d06,d08,"
    "gp_e8,seed,registered,cpu_count,human_count,net_humans,"
    "f58,f5c,f60,f64,f68,f6c,f70,f74,f78,f7c,f80,f9c,scope_flags,"
    "a0,a1,a2,a3,v0,v1,d3a,path_generation,d3e,d42,d43,d44,d48,"
    "e84,e86,graph_base,node0,node1,node2,node3,node4,node5,node6\n";
  aiProfileCsv_.flush();
  return true;
}

void NetBridge::drainAiProfile(uint8_t* ram,size_t ramSize){
  if(!ram||ramSize<kAiProfileEnd||!aiProfileCsv_)return;
  if(readU32(ram+kAiProfileBase)!=kAiProfileMagic||
     readU32(ram+kAiProfileBase+4)!=kAiProfileVersion||
     readU32(ram+kAiProfileBase+8)!=aiProfileGeneration_)return;

  const uint32_t total=readU32(ram+kAiProfileBase+0x10);
  if(total<aiProfileNextEvent_)aiProfileNextEvent_=total;
  uint64_t dropped=0;
  if(total-aiProfileNextEvent_>kAiProfileEventCount){
    dropped=total-aiProfileNextEvent_-kAiProfileEventCount;
    aiProfileNextEvent_=total-kAiProfileEventCount;
  }

  auto hex32=[&](uint32_t value){
    std::ostringstream output;
    output<<"0x"<<std::hex<<std::uppercase<<std::setw(8)<<std::setfill('0')<<value;
    return output.str();
  };
  auto read64=[](const uint8_t* source){
    return static_cast<uint64_t>(readU32(source))|
           (static_cast<uint64_t>(readU32(source+4))<<32);
  };

  uint32_t written=0;
  for(uint32_t logical=aiProfileNextEvent_;logical<total;++logical){
    const uint8_t* entry=ram+kAiProfileEventsOffset+
      static_cast<size_t>(logical&kAiProfileEventMask)*kAiProfileEventSize;
    if(readU32(entry)!=logical+1){dropped++;continue;}
    const uint32_t target=readU32(entry+0x04);
    const uint32_t packedPhases=readU32(entry+0x50);
    aiProfileCsv_<<std::dec<<logical+1<<","<<target<<","<<aiProfileTargetName(target)
      <<","<<(readU32(entry+0x08)==1?"enter":"exit")
      <<","<<hex32(readU32(entry+0x0C))
      <<","<<hex32(readU32(entry+0x10))
      <<","<<hex32(readU32(entry+0x14))
      <<","<<hex32(readU32(entry+0x18))
      <<","<<readU32(entry+0x1C)
      <<","<<read64(entry+0x20)
      <<","<<read64(entry+0x28)
      <<","<<readU32(entry+0x30)
      <<","<<readU32(entry+0x34)
      <<","<<readU32(entry+0x38)
      <<","<<hex32(readU32(entry+0x3C))
      <<","<<readU32(entry+0x40)
      <<","<<readU32(entry+0x44)
      <<","<<readU32(entry+0x48)
      <<","<<hex32(readU32(entry+0x4C))
      <<","<<(packedPhases&0xFFFFu)
      <<","<<(packedPhases>>16)
      <<","<<readU32(entry+0x54)
      <<","<<hex32(readU32(entry+0x58))
      <<","<<readU32(entry+0x5C)
      <<","<<readU32(entry+0x60)
      <<","<<readU32(entry+0x64)
      <<","<<readU32(entry+0x68);
    for(size_t offset=0x6C;offset<=0x98;offset+=4)
      aiProfileCsv_<<","<<hex32(readU32(entry+offset));
    aiProfileCsv_<<","<<hex32(readU32(entry+0x9C));
    for(size_t offset=0xA0;offset<=0xB4;offset+=4)
      aiProfileCsv_<<","<<hex32(readU32(entry+offset));
    const uint32_t packedPath=readU32(entry+0xB8);
    const uint32_t packedVehicle=readU32(entry+0xBC);
    const uint32_t packedRoute=readU32(entry+0xC8);
    aiProfileCsv_<<","<<(packedPath&0xFFFFu)
      <<","<<(packedPath>>16)
      <<","<<(packedVehicle&0xFFFFu)
      <<","<<((packedVehicle>>16)&0xFFu)
      <<","<<(packedVehicle>>24)
      <<","<<hex32(readU32(entry+0xC0))
      <<","<<hex32(readU32(entry+0xC4))
      <<","<<(packedRoute&0xFFFFu)
      <<","<<(packedRoute>>16)
      <<","<<hex32(readU32(entry+0xCC));
    for(size_t offset=0xD0;offset<=0xE8;offset+=4)
      aiProfileCsv_<<","<<hex32(readU32(entry+offset));
    aiProfileCsv_<<"\n";
    written++;
  }
  aiProfileNextEvent_=total;
  aiProfileEventCount_.store(total,std::memory_order_release);
  if(dropped)aiProfileDroppedEvents_.fetch_add(dropped,std::memory_order_acq_rel);
  // Flush periódico y determinista: permite inspeccionar capturas vivas sin
  // pagar un flush por frame. El destructor conserva el flush final.
  if(written&&((aiProfilePolls_&0x3Fu)==0))aiProfileCsv_.flush();

  aiProfilePolls_++;
  if((aiProfilePolls_&0xFFu)==0)
    writeU32(ram+kAiProfileBase+0x3C,readU32(ram+kAiProfileBase+0x3C)+1);

  const uint32_t histogramSequence=readU32(ram+kAiProfileBase+0x38);
  aiProfileHistogramSequence_.store(histogramSequence,std::memory_order_release);
  if(histogramSequence!=0&&histogramSequence!=aiProfileLastHistogramSequence_){
    dumpAiProfileHistogram(ram,ramSize,histogramSequence);
    aiProfileLastHistogramSequence_=histogramSequence;
  }
}

void NetBridge::dumpAiProfileHistogram(const uint8_t* ram,size_t ramSize,uint32_t sequence){
  if(!ram||ramSize<kAiProfileEnd)return;
  const auto directory=executableDirectory();
  if(directory.empty())return;
  const auto prefix=transportHost_?
    (aiProfileV3Executable()?L"TM3Online_Oscar.aiprofilev3":L"TM3Online_Oscar.aiprofile"):
    (aiProfileV3Executable()?L"TM3Online_Sofia.aiprofilev3":L"TM3Online_Sofia.aiprofile");
  const auto binaryPath=directory/(std::wstring(prefix)+L".hist.bin");
  const auto metaPath=directory/(std::wstring(prefix)+L".meta.txt");
  std::ofstream binary(binaryPath,std::ios::binary|std::ios::out|std::ios::trunc);
  if(binary)binary.write(reinterpret_cast<const char*>(ram+kAiProfileHistogramOffset),
                         static_cast<std::streamsize>(kAiProfileHistogramBytes));
  std::ofstream meta(metaPath,std::ios::out|std::ios::trunc);
  if(meta){
    const uint64_t instructions=static_cast<uint64_t>(readU32(ram+kAiProfileBase+0x20))|
      (static_cast<uint64_t>(readU32(ram+kAiProfileBase+0x24))<<32);
    meta<<"format=TM3O_AI_PROFILE_V3\n"
      <<"collector=beetle_precise_interpreter\n"
      <<"scus=RNGCaller_v12\n"
      <<"generation="<<aiProfileGeneration_<<"\n"
      <<"events="<<readU32(ram+kAiProfileBase+0x10)<<"\n"
      <<"dropped_events="<<aiProfileDroppedEvents_.load(std::memory_order_acquire)<<"\n"
      <<"instructions="<<instructions<<"\n"
      <<"histogram_sequence="<<sequence<<"\n"
      <<"pc_begin=0x80010000\n"
      <<"pc_end_exclusive=0x80070000\n"
      <<"categories=vehicle_update,cpu_callback,path_search,post_control\n"
      <<"emulated_timing_modified=no\n";
  }
}

void NetBridge::setStatus(std::string value){
  std::scoped_lock lock(mutex_);
  status_=std::move(value);
}

void NetBridge::openTrace(const wchar_t* filename){
  if(!tm3DiagnosticsEnabled())return;
  std::array<wchar_t,32768> modulePath{};
  const DWORD length=GetModuleFileNameW(nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  if(length==0)return;
  auto path=std::filesystem::path(std::wstring(modulePath.data(),length)).parent_path()/filename;
#ifdef TM3ONLINE_TESTING
  // Auxiliary disconnect-test bridges must not truncate the stress-run log.
  while(std::filesystem::exists(path))path+=L".aux";
#endif
  trace_.open(path,std::ios::out|std::ios::trunc);
}

void NetBridge::trace(std::string line){
  if(!trace_||traceEvents_>=kTraceLimit)return;
  trace_<<line<<'\n';
  ++traceEvents_;
  if(traceEvents_%kTraceFlushInterval==0)trace_.flush();
}

void NetBridge::dumpRngCallerRing(const uint8_t* ram,size_t ramSize,uint32_t ordinal,
                                  uint32_t localTime,uint32_t localRandom,
                                  uint32_t peerTime,uint32_t peerRandom){
  if(!tm3DiagnosticsEnabled())return;
  bool expected=false;
  if(!rngDumped_.compare_exchange_strong(
       expected,true,std::memory_order_acq_rel,std::memory_order_acquire))return;
  if(!ram||ramSize<kRngRingEnd||
     readU32(ram+kRngMagicOffset)!=kRngDiagMagic){
    trace("RNG_CALLER_DUMP_FAILED ord="+std::to_string(ordinal)+" reason=RAM");
    if(trace_)trace_.flush();
    return;
  }

  const auto directory=executableDirectory();
  if(directory.empty()){
    trace("RNG_CALLER_DUMP_FAILED ord="+std::to_string(ordinal)+" reason=PATH");
    if(trace_)trace_.flush();
    return;
  }
  const bool coreTrace=rngCoreTraceExecutable();
  const bool aiProfile=aiProfileExecutable();
  const bool aiProfileV3=aiProfileV3Executable();
  const auto prefix=transportHost_?
    (aiProfileV3?L"TM3Online_Oscar.aiprofilev3":
     aiProfile?L"TM3Online_Oscar.aiprofile":
     coreTrace?L"TM3Online_Oscar.rngcoretrace":L"TM3Online_Oscar"):
    (aiProfileV3?L"TM3Online_Sofia.aiprofilev3":
     aiProfile?L"TM3Online_Sofia.aiprofile":
     coreTrace?L"TM3Online_Sofia.rngcoretrace":L"TM3Online_Sofia");
  const auto rawPath=directory/(std::wstring(prefix)+L".rngcaller.ring.bin");
  const auto csvPath=directory/(std::wstring(prefix)+L".rngcaller.calls.csv");
  const auto metaPath=directory/(std::wstring(prefix)+L".rngcaller.meta.txt");

  const uint32_t totalCalls=readU32(ram+kRngCounterOffset);
  const uint32_t validCalls=std::min(totalCalls,kRngEntryCount);
  const uint32_t firstLogical=totalCalls-validCalls;

  std::ofstream raw(rawPath,std::ios::binary|std::ios::out|std::ios::trunc);
  if(raw)raw.write(reinterpret_cast<const char*>(ram+kRngCounterOffset),
                   static_cast<std::streamsize>(kRngRingEnd-kRngCounterOffset));

  std::ofstream csv(csvPath,std::ios::out|std::ios::trunc);
  if(csv){
    csv<<"logical_call,ring_index,ra,caller_jal,seed_before,seed_after,aux0,aux1\n";
    for(uint32_t logical=firstLogical;logical<totalCalls;++logical){
      const uint32_t index=logical&kRngEntryMask;
      const uint8_t* entry=ram+kRngEntriesOffset+
        static_cast<size_t>(index)*kRngEntrySize;
      const uint32_t ra=readU32(entry);
      const uint32_t seed=readU32(entry+4);
      const uint32_t aux0=readU32(entry+8);
      const uint32_t aux1=readU32(entry+12);
      const uint32_t after=seed*0x41C64E6Du+12345u;
      csv<<std::dec<<logical+1<<","<<index<<",0x"
        <<std::hex<<std::uppercase<<std::setw(8)<<std::setfill('0')<<ra
        <<",0x"<<std::setw(8)<<(ra-8u)
        <<",0x"<<std::setw(8)<<seed
        <<",0x"<<std::setw(8)<<after
        <<",0x"<<std::setw(8)<<aux0
        <<",0x"<<std::setw(8)<<aux1<<"\n";
    }
  }

  std::ofstream meta(metaPath,std::ios::out|std::ios::trunc);
  if(meta){
    meta<<"format=TM3O_RNG_CALLER_V1\n"
      <<"collector="<<(coreTrace?"beetle_interpreter":"scus_codecave")<<"\n"
      <<"ordinal="<<std::dec<<ordinal<<"\n"
      <<"total_calls="<<totalCalls<<"\n"
      <<"valid_ring_calls="<<validCalls<<"\n"
      <<"first_logical_call="<<firstLogical+1<<"\n"
      <<"local_time=0x"<<std::hex<<std::uppercase<<localTime<<"\n"
      <<"local_random=0x"<<localRandom<<"\n"
      <<"peer_time=0x"<<peerTime<<"\n"
      <<"peer_random=0x"<<peerRandom<<"\n"
      <<"raw_offset_start=0x80F00010\n"
      <<"raw_offset_end_exclusive=0x80F10020\n"
      <<"codecave=0x80F10100\n"
      <<"aux0="<<(coreTrace?"interpreter_timestamp":"zero")<<"\n"
      <<"aux1="<<(coreTrace?"gpr_sp":"zero")<<"\n";
  }
  trace("RNG_CALLER_DUMP ord="+std::to_string(ordinal)+
    " calls="+std::to_string(totalCalls)+" valid="+std::to_string(validCalls));
  if(trace_)trace_.flush();
}

void NetBridge::closeSockets(){
  if(udp_!=INVALID_SOCKET){closesocket(udp_);udp_=INVALID_SOCKET;}
  if(tcp_!=INVALID_SOCKET){closesocket(tcp_);tcp_=INVALID_SOCKET;}
  if(listen_!=INVALID_SOCKET){closesocket(listen_);listen_=INVALID_SOCKET;}
}

bool NetBridge::openUdp(uint16_t requestedPort,uint16_t& boundPort){
  udp_=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
  if(udp_==INVALID_SOCKET)return false;
  int socketBuffer=1<<20;
  setsockopt(udp_,SOL_SOCKET,SO_RCVBUF,reinterpret_cast<const char*>(&socketBuffer),sizeof(socketBuffer));
  setsockopt(udp_,SOL_SOCKET,SO_SNDBUF,reinterpret_cast<const char*>(&socketBuffer),sizeof(socketBuffer));
  sockaddr_in local{};
  local.sin_family=AF_INET;
  local.sin_addr.s_addr=htonl(INADDR_ANY);
  local.sin_port=htons(requestedPort);
  if(bind(udp_,reinterpret_cast<const sockaddr*>(&local),sizeof(local))!=0)return false;
  int length=sizeof(local);
  if(getsockname(udp_,reinterpret_cast<sockaddr*>(&local),&length)!=0)return false;
  boundPort=ntohs(local.sin_port);
  u_long nonBlocking=1;
  return ioctlsocket(udp_,FIONBIO,&nonBlocking)==0;
}

void NetBridge::workerHost(uint16_t port,std::stop_token stop){
  uint16_t udpPort=0;
  if(!openUdp(port,udpPort)){setStatus("error abriendo UDP");return;}
  listen_=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
  if(listen_==INVALID_SOCKET){setStatus("error abriendo TCP");return;}
  int yes=1;
  setsockopt(listen_,SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<const char*>(&yes),sizeof(yes));
  sockaddr_in local{};
  local.sin_family=AF_INET;
  local.sin_addr.s_addr=htonl(INADDR_ANY);
  local.sin_port=htons(port);
  if(bind(listen_,reinterpret_cast<const sockaddr*>(&local),sizeof(local))!=0||listen(listen_,1)!=0){
    setStatus("error reservando puerto TCP");return;
  }
  setStatus("esperando jugador por TCP");
  sockaddr_in remote{};
  int remoteLength=sizeof(remote);
  tcp_=accept(listen_,reinterpret_cast<sockaddr*>(&remote),&remoteLength);
  if(tcp_==INVALID_SOCKET||stop.stop_requested())return;
  int one=1;
  setsockopt(tcp_,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<const char*>(&one),sizeof(one));

  Control hello{};
  if(!recvAll(&hello,sizeof(hello))||hello.magic!=kMagic||hello.version!=kProtocolVersion||
     hello.kind!=kHello||hello.udpPort==0||hello.udpPort>0xFFFFu){
    setStatus("handshake TCP invalido");return;
  }
  peerUdp_=remote;
  peerUdp_.sin_port=htons(static_cast<uint16_t>(hello.udpPort));
  std::random_device random;
  session_=(static_cast<uint64_t>(random())<<32)|random();
  if(session_==0)session_=1;
  const Control accept{kMagic,kProtocolVersion,kAccept,udpPort,0,session_};
  if(!sendAll(&accept,sizeof(accept))){setStatus("fallo enviando handshake TCP");return;}
  connected_.store(true,std::memory_order_release);
  setStatus("conectado: TCP sesion / UDP gameplay");
  sessionLoop(stop);
}

void NetBridge::workerJoin(std::string host,uint16_t port,std::stop_token stop){
  uint16_t udpPort=0;
  if(!openUdp(0,udpPort)){setStatus("error abriendo UDP");return;}
  addrinfo hints{};
  hints.ai_family=AF_INET;
  hints.ai_socktype=SOCK_STREAM;
  hints.ai_protocol=IPPROTO_TCP;
  addrinfo* addresses=nullptr;
  const auto service=std::to_string(port);
  if(getaddrinfo(host.c_str(),service.c_str(),&hints,&addresses)!=0){setStatus("host no encontrado");return;}
  for(auto* address=addresses;address;address=address->ai_next){
    tcp_=socket(address->ai_family,address->ai_socktype,address->ai_protocol);
    if(tcp_!=INVALID_SOCKET&&connect(tcp_,address->ai_addr,static_cast<int>(address->ai_addrlen))==0)break;
    if(tcp_!=INVALID_SOCKET)closesocket(tcp_);
    tcp_=INVALID_SOCKET;
  }
  freeaddrinfo(addresses);
  if(tcp_==INVALID_SOCKET||stop.stop_requested()){setStatus("no se pudo conectar por TCP");return;}
  int one=1;
  setsockopt(tcp_,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<const char*>(&one),sizeof(one));
  int peerLength=sizeof(peerUdp_);
  if(getpeername(tcp_,reinterpret_cast<sockaddr*>(&peerUdp_),&peerLength)!=0){setStatus("peer TCP invalido");return;}
  const Control hello{kMagic,kProtocolVersion,kHello,udpPort,0,0};
  Control accept{};
  if(!sendAll(&hello,sizeof(hello))||!recvAll(&accept,sizeof(accept))||
     accept.magic!=kMagic||accept.version!=kProtocolVersion||accept.kind!=kAccept||
     accept.udpPort==0||accept.udpPort>0xFFFFu||accept.session==0){
    setStatus("handshake TCP invalido");return;
  }
  peerUdp_.sin_port=htons(static_cast<uint16_t>(accept.udpPort));
  session_=accept.session;
  connected_.store(true,std::memory_order_release);
  setStatus("conectado: TCP sesion / UDP gameplay");
  sessionLoop(stop);
}

void NetBridge::sessionLoop(std::stop_token stop){
  wchar_t mode[8]{};
  const bool fast=GetEnvironmentVariableW(L"TM3O_LINK_HIRES_WAIT",mode,8)==1&&mode[0]==L'1';
  HANDLE timer=fast?CreateWaitableTimerExW(nullptr,nullptr,CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                         TIMER_MODIFY_STATE|SYNCHRONIZE):nullptr;
  trace(std::string("LINK_WAIT_MODE mode=")+(timer?"hires_1ms":"legacy_sleep_1ms")+
        " requested="+(fast?"hires":"legacy"));
  wchar_t wakeMode[8]{};
  const bool wakeRequested=GetEnvironmentVariableW(L"TM3O_LINK_UDP_WAKE",wakeMode,8)==1&&wakeMode[0]==L'1';
  bool udpWake=false;
  if(wakeRequested){
    udpReadEvent_=WSACreateEvent();
    udpWake=udpReadEvent_!=WSA_INVALID_EVENT&&
            WSAEventSelect(udp_,udpReadEvent_,FD_READ)==0;
  }
  trace(std::string("LINK_UDP_WAKE active=")+(udpWake?"1":"0")+
        " requested="+(wakeRequested?"1":"0")+
        " fallback="+(wakeRequested&&!udpWake?"event_setup_failed":"none"));
  uint64_t timerWakes=0;
  auto previous=std::chrono::steady_clock::now();
  while(!stop.stop_requested()){
    const auto now=std::chrono::steady_clock::now();
    diagnosticLoopUs_=std::chrono::duration<double,std::micro>(now-previous).count();
    previous=now;
    if(pending_)pending_->diagnosticMaxLoopUs=std::max(pending_->diagnosticMaxLoopUs,diagnosticLoopUs_);
    processTcpControls();
    if(returnRequested_.exchange(false)){
      const Control cancel{kMagic,kProtocolVersion,kReturnToMenu,0,0,session_};
      sendAll(&cancel,sizeof(cancel));
      returnReady_.store(true);
    }
    if(udpWake){
      // Atomically acknowledge recorded events before draining recvfrom. Do not
      // ResetEvent after draining: that could erase a just-arrived notification.
      WSANETWORKEVENTS events{};
      if(WSAEnumNetworkEvents(udp_,udpReadEvent_,&events)==SOCKET_ERROR){
        if(!stop.stop_requested())WSAEventSelect(udp_,nullptr,0);
        udpWake=false;
        trace("LINK_UDP_WAKE active=0 reason=enum_failure fallback=poll");
      }
    }
    receiveDatagrams();
    processMailbox();
    if(timer){
      LARGE_INTEGER due{};
      due.QuadPart=-10000; // Relative 1 ms, in 100 ns units; not a guest clock.
      if(SetWaitableTimer(timer,&due,0,nullptr,nullptr,FALSE)){
        const HANDLE waits[]{timer,udpReadEvent_};
        const DWORD result=WaitForMultipleObjects(udpWake?2:1,waits,FALSE,100);
        if(result==WAIT_OBJECT_0){++timerWakes;continue;}
        if(udpWake&&result==WAIT_OBJECT_0+1){
          udpWakeCount_.fetch_add(1,std::memory_order_relaxed);
          continue;
        }
      }
      CloseHandle(timer);
      timer=nullptr;
      trace("LINK_WAIT_MODE mode=legacy_sleep_1ms reason=timer_failure");
    }
    if(udpWake){
      const DWORD result=WaitForSingleObject(udpReadEvent_,1);
      if(result==WAIT_OBJECT_0){
        udpWakeCount_.fetch_add(1,std::memory_order_relaxed);
        continue;
      }
      if(result==WAIT_TIMEOUT){++timerWakes;continue;}
      if(!stop.stop_requested())WSAEventSelect(udp_,nullptr,0);
      udpWake=false;
      trace("LINK_UDP_WAKE active=0 reason=wait_failure fallback=poll");
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  if(timer)CloseHandle(timer);
  trace("LINK_UDP_WAKE_STATS udp="+std::to_string(udpWakeCount_.load(std::memory_order_relaxed))+
        " timer="+std::to_string(timerWakes));
  connected_.store(false,std::memory_order_release);
  setStatus("desconectado");
}

void NetBridge::processTcpControls(){
  if(tcp_==INVALID_SOCKET)return;
  for(;;){
    u_long available=0;
    if(ioctlsocket(tcp_,FIONREAD,&available)!=0){
      connected_.store(false,std::memory_order_release);
      setStatus("error consultando sesion TCP");
      return;
    }
    if(available<sizeof(Control)){
      // SIO_STAT.7 reflejaba el DTR remoto como una señal de nivel. TCP debe
      // retirar el equivalente TM3O.flags cuando el peer cierra la sesión,
      // incluso si no quedó ningún Control pendiente para leer.
      if(tcpPeerClosed(tcp_)){
        connected_.store(false,std::memory_order_release);
        setStatus("peer TCP desconectado");
      }
      return;
    }
    Control control{};
    if(!recvAll(&control,sizeof(control))){
      connected_.store(false,std::memory_order_release);
      setStatus("peer TCP desconectado");
      return;
    }
    if(control.magic!=kMagic||control.version!=kProtocolVersion||control.session!=session_)continue;
    if(control.kind==kReturnToMenu){
      returnReady_.store(true);
    }else if(transportHost_&&control.kind==kRoleReady){
      remoteRoleRound_=control.udpPort;
      remoteRoleWaiting_=true;
      remoteRoleOrder_=++roleOrder_;
      trace("ROLE_READY remoto round="+std::to_string(remoteRoleRound_)+
        " order="+std::to_string(remoteRoleOrder_));
      assignRolesIfReady();
    }else if(!transportHost_&&control.kind==kRoleAssign&&localRoleWaiting_&&
             control.udpPort==localRoleRound_&&(control.reserved==1||control.reserved==2)){
      localRole_.store(static_cast<uint16_t>(control.reserved),std::memory_order_release);
      localRoleWaiting_=false;
      trace("ROLE_ASSIGN recibido round="+std::to_string(control.udpPort)+
        " role="+std::to_string(control.reserved));
    }
  }
}

void NetBridge::receiveDatagrams(){
  std::array<uint8_t,sizeof(Wire)+kFragmentPayload> datagram{};
  for(;;){
    sockaddr_in sender{};
    int senderLength=sizeof(sender);
    const int received=recvfrom(udp_,reinterpret_cast<char*>(datagram.data()),
      static_cast<int>(datagram.size()),0,reinterpret_cast<sockaddr*>(&sender),&senderLength);
    if(received<0){
      const int error=WSAGetLastError();
      if(error==WSAEWOULDBLOCK)return;
      return;
    }
    if(static_cast<size_t>(received)<sizeof(Wire)||sender.sin_addr.s_addr!=peerUdp_.sin_addr.s_addr||
       sender.sin_port!=peerUdp_.sin_port)continue;
    Wire wire{};
    std::memcpy(&wire,datagram.data(),sizeof(wire));
    if(wire.magic!=kMagic||wire.version!=kProtocolVersion||wire.session!=session_||wire.ordinal==0||
       (wire.command!=kTransfer&&wire.command!=kBatchTransfer)||
       wire.payloadSize>kMaxPayload||wire.expectedSize>kMaxPayload||
       wire.fragmentSize>kFragmentPayload||
       static_cast<size_t>(received)!=sizeof(Wire)+wire.fragmentSize)continue;
    const uint32_t fragmentCount=wire.payloadSize==0?1u:
      static_cast<uint32_t>((wire.payloadSize+kFragmentPayload-1)/kFragmentPayload);
    if(wire.payloadSize==0){
      if(wire.fragmentOffset!=0||wire.fragmentSize!=0)continue;
    }else{
      if(wire.fragmentOffset%kFragmentPayload!=0||wire.fragmentOffset>=wire.payloadSize)continue;
      const uint32_t expectedFragment=static_cast<uint32_t>(std::min<size_t>(
        kFragmentPayload,wire.payloadSize-wire.fragmentOffset));
      if(wire.fragmentSize!=expectedFragment)continue;
    }
    udpReceived_.fetch_add(1,std::memory_order_relaxed);
    const bool request=wire.replyTo==0;
    const uint32_t key=request?wire.sequence:wire.replyTo;
    auto& destination=request?incomingRequests_:incomingResponses_;
    auto found=destination.find(key);
    if(found==destination.end()){
      Incoming incoming{};
      incoming.command=wire.command;
      incoming.sequence=wire.sequence;
      incoming.replyTo=wire.replyTo;
      incoming.ordinal=wire.ordinal;
      incoming.expectedSize=wire.expectedSize;
      incoming.callSite=wire.callSite;
      incoming.crc=wire.crc;
      incoming.payload.resize(wire.payloadSize);
      incoming.receivedFragments.assign(fragmentCount,0);
      incoming.fragmentCount=fragmentCount;
      found=destination.emplace(key,std::move(incoming)).first;
    }
    auto& incoming=found->second;
    if(incoming.command!=wire.command||incoming.sequence!=wire.sequence||
       incoming.replyTo!=wire.replyTo||incoming.ordinal!=wire.ordinal||
       incoming.expectedSize!=wire.expectedSize||
       incoming.callSite!=wire.callSite||incoming.crc!=wire.crc||
       incoming.payload.size()!=wire.payloadSize||incoming.fragmentCount!=fragmentCount){
      destination.erase(found);
      continue;
    }
    if(incoming.complete){
      if(request){
        const auto replay=responseReplay_.find(wire.sequence);
        if(replay!=responseReplay_.end())sendPacket(replay->second);
      }
      continue;
    }
    const uint32_t fragmentIndex=wire.payloadSize==0?0u:
      static_cast<uint32_t>(wire.fragmentOffset/kFragmentPayload);
    if(fragmentIndex>=incoming.receivedFragments.size()){
      destination.erase(found);
      continue;
    }
    if(!incoming.receivedFragments[fragmentIndex]){
      if(wire.fragmentSize)std::memcpy(incoming.payload.data()+wire.fragmentOffset,
        datagram.data()+sizeof(Wire),wire.fragmentSize);
      incoming.receivedFragments[fragmentIndex]=1;
      ++incoming.receivedCount;
    }
    if(incoming.receivedCount!=incoming.fragmentCount)continue;
    if(crc32(incoming.payload.data(),incoming.payload.size())!=incoming.crc){
      destination.erase(found);
      continue;
    }
    incoming.complete=true;
    incoming.diagnosticReady=std::chrono::steady_clock::now();
    if(request){
      const auto replay=responseReplay_.find(wire.sequence);
      if(replay!=responseReplay_.end()){
        sendPacket(replay->second);
        destination.erase(found);
        continue;
      }
    }
    if(destination.size()>64)destination.erase(destination.begin());
  }
}

bool NetBridge::beginRoleNegotiation(){
  roleRequests_.fetch_add(1,std::memory_order_relaxed);

  // El rol pertenece a la sesion enlazada, no a cada reentrada de
  // 0x80047D3C. El SIO fisico conserva DTR/DSR y el estado de ambos extremos
  // mientras el cable sigue conectado. TM3 puede volver al inicio de esta
  // rutina si esta repitiendo el intercambio del rol anterior o del token
  // 0x45; borrar aqui un rol ya confirmado iniciaba otra ronda y dejaba a
  // ambas consolas negociando indefinidamente.
  const uint16_t assignedRole=localRole_.load(std::memory_order_acquire);
  if(assignedRole==1||assignedRole==2){
    trace("ROLE_REUSE role="+std::to_string(assignedRole)+
      " round="+std::to_string(localRoleRound_));
    return true;
  }
  if(localRoleWaiting_){
    trace("ROLE_REUSE waiting round="+std::to_string(localRoleRound_));
    return true;
  }

  localRole_.store(0,std::memory_order_release);
  ++localRoleRound_;
  if(localRoleRound_==0)++localRoleRound_;
  localRoleWaiting_=true;
  localRoleOrder_=++roleOrder_;
  trace("ROLE_BEGIN local round="+std::to_string(localRoleRound_)+
    " order="+std::to_string(localRoleOrder_)+" remoteRound="+std::to_string(remoteRoleRound_));
  if(transportHost_){
    assignRolesIfReady();
    return true;
  }
  const Control ready{kMagic,kProtocolVersion,kRoleReady,localRoleRound_,0,session_};
  return sendAll(&ready,sizeof(ready));
}

void NetBridge::assignRolesIfReady(){
  if(!transportHost_||!localRoleWaiting_||!remoteRoleWaiting_||
     localRoleRound_!=remoteRoleRound_)return;
  // Lobby ownership determines authority, regardless of the order of Yes.
  const uint16_t localRole=2;
  const uint16_t remoteRole=1;
  trace("ROLE_SEND round="+std::to_string(localRoleRound_)+" local="+
    std::to_string(localRole)+" remote="+std::to_string(remoteRole)+" orders="+
    std::to_string(localRoleOrder_)+"/"+std::to_string(remoteRoleOrder_));
  const Control assignment{kMagic,kProtocolVersion,kRoleAssign,localRoleRound_,remoteRole,session_};
  if(!sendAll(&assignment,sizeof(assignment)))return;
  localRole_.store(localRole,std::memory_order_release);
  localRoleWaiting_=false;
  remoteRoleWaiting_=false;
}

void NetBridge::appendWaitTiming(std::ostringstream& line,const Incoming& incoming) const{
  const auto now=std::chrono::steady_clock::now();
  const auto us=[](auto duration){return std::chrono::duration<double,std::micro>(duration).count();};
  // Host observations only: neither packet kernel arrival nor guest resume.
  line<<std::dec<<" wait_us="<<us(now-pending_->diagnosticObserved)
      <<" ready_age_us="<<us(now-incoming.diagnosticReady)
      <<" worker_gap_max_us="<<pending_->diagnosticMaxLoopUs
      <<" retries="<<pending_->retransmissions
      <<" send_bytes="<<pending_->payload.size()<<" recv_bytes="<<incoming.payload.size()
      <<" observed_us="<<std::chrono::duration_cast<std::chrono::microseconds>(pending_->diagnosticObserved.time_since_epoch()).count()
      <<" ready_us="<<std::chrono::duration_cast<std::chrono::microseconds>(incoming.diagnosticReady.time_since_epoch()).count();
}

void NetBridge::processMailbox(){
  auto* ram=ram_.load(std::memory_order_acquire);
  const size_t ramSize=ramSize_.load(std::memory_order_acquire);
  if(!ram||ramSize<kMailboxOffset+sizeof(Mailbox))return;
  auto* mailbox=reinterpret_cast<Mailbox*>(ram+kMailboxOffset);
  if(mailbox->magic!=kMagic||mailbox->version!=kMailboxVersion)return;
  const bool connected=connected_.load(std::memory_order_acquire);
  const uint16_t role=localRole_.load(std::memory_order_acquire);
  // GP=0x800894C0; the original menu code reads its active table from GP+0x54C.
  // Observe only known menu addresses, after a linked menu was actually entered.
  if(connected&&ramSize>0x89A10){
    const uint32_t menu=readU32(ram+0x89A0C);
    if(menu==0x8007FF98||menu==0x8007FF64||(role&&menu==0x80080038))seenLinkedMenu_=true;
    if(seenLinkedMenu_&&(menu==0x8007FEDC||menu==0x8007FFE8)){
      seenLinkedMenu_=false;
      // A table transition also happens during normal level loading. Only a
      // recent, real Triangle press may turn that transition into cancellation.
      const auto now=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
      if(now<=triangleUntil_.exchange(0))returnRequested_.store(true);
    }
  }
  const uint16_t ramFlag=ramSize>=16*1024*1024?kExpandedRamFlag:0;
  writeMailboxFlags(mailbox,connected?static_cast<uint16_t>(kConnectedFlag|ramFlag|role):ramFlag);
  const auto fail=[this,mailbox](){
    pending_.reset();
    pendingRetransmissions_.store(0,std::memory_order_relaxed);
    errors_.fetch_add(1,std::memory_order_relaxed);
    writeMailboxStatus(mailbox,4);
  };
  const auto buildPending=[ram,ramSize,mailbox](Pending& pending){
    const auto appendSend=[ram,ramSize,&pending](uint32_t address,uint32_t size){
      size_t offset=0;
      if(!translateRamRange(ramSize,address,size,offset))return false;
      if(size)pending.payload.insert(pending.payload.end(),ram+offset,ram+offset+size);
      return true;
    };
    const auto appendReceive=[ramSize,&pending](uint32_t address,uint32_t size){
      size_t offset=0;
      if(!translateRamRange(ramSize,address,size,offset))return false;
      if(size)pending.recvRanges.push_back(RamRange{offset,size});
      return true;
    };
    pending.payload.reserve(mailbox->sendSize);
    if(mailbox->command==kTransfer){
      return appendSend(mailbox->sendAddress,mailbox->sendSize)&&
        appendReceive(mailbox->recvAddress,mailbox->recvCapacity)&&
        pending.payload.size()==mailbox->sendSize;
    }
    if(mailbox->command!=kBatchTransfer||mailbox->sendSegmentCount>4||
       mailbox->recvSegmentCount>4)return false;
    uint64_t sendTotal=0,recvTotal=0;
    for(uint32_t index=0;index<mailbox->sendSegmentCount;++index){
      const auto& segment=mailbox->sendSegments[index];
      sendTotal+=segment.size;
      if(sendTotal>kMaxPayload||!appendSend(segment.address,segment.size))return false;
    }
    for(uint32_t index=0;index<mailbox->recvSegmentCount;++index){
      const auto& segment=mailbox->recvSegments[index];
      recvTotal+=segment.size;
      if(recvTotal>kMaxPayload||!appendReceive(segment.address,segment.size))return false;
    }
    return sendTotal==mailbox->sendSize&&recvTotal==mailbox->recvCapacity&&
      pending.payload.size()==mailbox->sendSize;
  };
  const auto scatterReceive=[ram](const Pending& pending,const std::vector<uint8_t>& payload){
    size_t position=0;
    for(const auto& range:pending.recvRanges){
      if(position>payload.size())return false;
      const size_t count=std::min<size_t>(range.size,payload.size()-position);
      if(count)std::memcpy(ram+range.offset,payload.data()+position,count);
      position+=count;
      if(position==payload.size())break;
    }
    return position==payload.size();
  };

  uint16_t mailboxStatus=readMailboxStatus(mailbox);
  if(!connected&&(mailboxStatus==1||mailboxStatus==2)){
    fail();return;
  }
  if(mailboxStatus==1){
    if(mailbox->command==kRoleRequest){
      pending_.reset();
      pendingRetransmissions_.store(0,std::memory_order_relaxed);
      if(!beginRoleNegotiation()){fail();return;}
      writeMailboxFlags(mailbox,static_cast<uint16_t>(kConnectedFlag|ramFlag));
      writeMailboxStatus(mailbox,2);
      mailboxStatus=2;
    }else if((mailbox->command!=kTransfer&&mailbox->command!=kBatchTransfer)||
             mailbox->sendSize>kMaxPayload||mailbox->recvCapacity>kMaxPayload){
      fail();return;
    }else{
      Pending pending{};
      pending.diagnosticObserved=std::chrono::steady_clock::now();
      if(boundaryEnabled())pending.diagnosticObservedQpc=boundaryQpc();
      pending.diagnosticMaxLoopUs=diagnosticLoopUs_;
      pending.command=mailbox->command;
      pending.replyTo=0;
      pending.expectedSize=mailbox->recvCapacity;
      pending.callSite=mailbox->callSite;
      auto& ordinal=callOrdinals_[pending.callSite];
      ++ordinal;
      if(ordinal==0)++ordinal;
      pending.ordinal=ordinal;
      if(!buildPending(pending)){fail();return;}
      ++nextSequence_;
      if(nextSequence_==0)++nextSequence_;
      mailbox->sequence=nextSequence_;
      pending.sequence=mailbox->sequence;
      pending.lastSent=std::chrono::steady_clock::now();
      requests_.fetch_add(1,std::memory_order_relaxed);
      lastSendSize_.store(mailbox->sendSize,std::memory_order_relaxed);
      lastRecvCapacity_.store(mailbox->recvCapacity,std::memory_order_relaxed);
      lastCallSite_.store(mailbox->callSite,std::memory_order_relaxed);
      lastOrdinal_.store(pending.ordinal,std::memory_order_relaxed);
      pendingRetransmissions_.store(0,std::memory_order_relaxed);
      lastSendWord_.store(firstWord(pending.payload.data(),pending.payload.size()),std::memory_order_relaxed);
      {
        std::ostringstream line;
        line<<"TX seq="<<mailbox->sequence<<" ord="<<pending.ordinal
          <<" call="<<std::hex<<std::uppercase<<mailbox->callSite
          <<" sizes="<<std::dec<<mailbox->sendSize<<"/"<<mailbox->recvCapacity
          <<" mode="<<(mailbox->command==kBatchTransfer?"BATCH":"DIRECT")
          <<" word="<<std::hex<<firstWord(pending.payload.data(),pending.payload.size());
        if(mailbox->command==kBatchTransfer&&mailbox->callSite==kGameplayBatchReturn){
          appendGameplaySyncTail(line,"local",gameplaySyncTail(pending.payload));
        }
        trace(line.str());
      }
      pending_=std::move(pending);
      if(boundaryEnabled() && pending_->callSite==kGameplayBatchReturn){
        LARGE_INTEGER hz{};QueryPerformanceFrequency(&hz);
        trace("LINK_DETECT seq="+std::to_string(pending_->sequence)+" qpc="+std::to_string(pending_->diagnosticObservedQpc)+" hz="+std::to_string(hz.QuadPart));
      }
      if(!sendPacket(*pending_)){fail();return;}
      writeMailboxStatus(mailbox,2);
      mailboxStatus=2;
    }
  }

  if(mailboxStatus!=2)return;
  if(mailbox->command==kRoleRequest){
    const uint16_t assignedRole=localRole_.load(std::memory_order_acquire);
    if(assignedRole==0)return;
    mailbox->recvSize=0;
    writeMailboxFlags(mailbox,static_cast<uint16_t>(kConnectedFlag|ramFlag|assignedRole));
    writeMailboxStatus(mailbox,3);
    return;
  }
  if(!pending_||pending_->sequence!=mailbox->sequence){fail();return;}
  // Una respuesta identifica exactamente nuestra solicitud mediante replyTo.
  // No exige que el contador de secuencia remoto coincida con el local.
  auto foundResponse=incomingResponses_.find(mailbox->sequence);
  if(foundResponse!=incomingResponses_.end()&&foundResponse->second.complete){
    if(foundResponse->second.command!=mailbox->command||
       foundResponse->second.ordinal!=pending_->ordinal||
       foundResponse->second.callSite!=pending_->callSite||
       foundResponse->second.payload.size()>mailbox->recvCapacity||
       pending_->payload.size()>foundResponse->second.expectedSize){
      incomingResponses_.erase(foundResponse);fail();return;
    }
    const uint32_t remoteSequence=foundResponse->second.sequence;
    if(!scatterReceive(*pending_,foundResponse->second.payload)){
      incomingResponses_.erase(foundResponse);fail();return;
    }
    lastRecvWord_.store(firstWord(foundResponse->second.payload.data(),foundResponse->second.payload.size()),
      std::memory_order_relaxed);
    lastRemoteOrdinal_.store(foundResponse->second.ordinal,std::memory_order_relaxed);
    {
      std::ostringstream line;
      line<<"RX_RESPONSE seq="<<mailbox->sequence<<" ord="<<pending_->ordinal
        <<" remote-ord="<<foundResponse->second.ordinal
        <<" call="<<std::hex<<std::uppercase<<mailbox->callSite
        <<" word="<<firstWord(foundResponse->second.payload.data(),foundResponse->second.payload.size());
      if(mailbox->command==kBatchTransfer&&mailbox->callSite==kGameplayBatchReturn){
        const auto sync=appendGameplaySyncComparison(
          line,pending_->payload,foundResponse->second.payload);
        if(sync==GameplaySyncStatus::RandomMismatch){
          const auto local=gameplaySyncTail(pending_->payload);
          const auto peer=gameplaySyncTail(foundResponse->second.payload);
          dumpRngCallerRing(ram,ramSize,pending_->ordinal,
            local.time,local.random,peer.time,peer.random);
        }
      }
      appendWaitTiming(line,foundResponse->second);
      trace(line.str());
    }
    mailbox->recvSize=static_cast<uint32_t>(foundResponse->second.payload.size());
    lastSequence_.store(mailbox->sequence,std::memory_order_relaxed);
    completed_.fetch_add(1,std::memory_order_relaxed);
    incomingResponses_.erase(foundResponse);
    // La respuesta y el REQUEST del par pueden llegar juntos. Ambos describen
    // la misma operacion remota; conservar el REQUEST lo haria parecer una
    // solicitud nueva en la siguiente llamada MIPS.
    incomingRequests_.erase(remoteSequence);
    pending_.reset();
    pendingRetransmissions_.store(0,std::memory_order_relaxed);
    writeMailboxStatus(mailbox,3);
    return;
  }

  // Si todavia no llego una respuesta, cualquier REQUEST remoto compatible
  // puede completar la operacion. El juego es sincrono, pero cada PS1 puede
  // haber ejecutado una llamada adicional y por eso sus secuencias divergen.
  auto foundRequest=incomingRequests_.end();
  for(auto it=incomingRequests_.begin();it!=incomingRequests_.end();++it){
    if(it->second.complete&&it->second.command==mailbox->command&&
       it->second.ordinal==pending_->ordinal&&
       it->second.callSite==pending_->callSite&&
       it->second.payload.size()<=mailbox->recvCapacity&&
       pending_->payload.size()<=it->second.expectedSize&&
       (foundRequest==incomingRequests_.end()||
        sequenceBefore(it->second.sequence,foundRequest->second.sequence))){
      // El SIO físico entrega un flujo FIFO. Si UDP dejó más de una
      // solicitud compatible en cola, conserva el orden lógico del emisor.
      foundRequest=it;
    }
  }
  if(foundRequest!=incomingRequests_.end()){
    Pending response=*pending_;
    response.replyTo=foundRequest->second.sequence;
    response.ordinal=foundRequest->second.ordinal;
    response.lastSent=std::chrono::steady_clock::now();
    if(!sendPacket(response)){incomingRequests_.erase(foundRequest);fail();return;}
    responseReplay_[foundRequest->second.sequence]=std::move(response);
    if(responseReplay_.size()>64)responseReplay_.erase(responseReplay_.begin());
    if(!scatterReceive(*pending_,foundRequest->second.payload)){
      incomingRequests_.erase(foundRequest);fail();return;
    }
    lastRecvWord_.store(firstWord(foundRequest->second.payload.data(),foundRequest->second.payload.size()),
      std::memory_order_relaxed);
    lastRemoteOrdinal_.store(foundRequest->second.ordinal,std::memory_order_relaxed);
    {
      std::ostringstream line;
      line<<"RX_REQUEST seq="<<mailbox->sequence<<" ord="<<pending_->ordinal
        <<" remote-ord="<<foundRequest->second.ordinal
        <<" call="<<std::hex<<std::uppercase<<mailbox->callSite
        <<" word="<<firstWord(foundRequest->second.payload.data(),foundRequest->second.payload.size());
      if(mailbox->command==kBatchTransfer&&mailbox->callSite==kGameplayBatchReturn){
        const auto sync=appendGameplaySyncComparison(
          line,pending_->payload,foundRequest->second.payload);
        if(sync==GameplaySyncStatus::RandomMismatch){
          const auto local=gameplaySyncTail(pending_->payload);
          const auto peer=gameplaySyncTail(foundRequest->second.payload);
          dumpRngCallerRing(ram,ramSize,pending_->ordinal,
            local.time,local.random,peer.time,peer.random);
        }
      }
      appendWaitTiming(line,foundRequest->second);
      trace(line.str());
    }
    mailbox->recvSize=static_cast<uint32_t>(foundRequest->second.payload.size());
    lastSequence_.store(mailbox->sequence,std::memory_order_relaxed);
    completed_.fetch_add(1,std::memory_order_relaxed);
    incomingRequests_.erase(foundRequest);
    pending_.reset();
    pendingRetransmissions_.store(0,std::memory_order_relaxed);
    writeMailboxStatus(mailbox,3);
    return;
  }

  const auto now=std::chrono::steady_clock::now();
  if(now-pending_->lastSent>=kRetransmitDelay){
    if(!sendPacket(*pending_)){fail();return;}
    pending_->lastSent=now;
    ++pending_->retransmissions;
    pendingRetransmissions_.store(pending_->retransmissions,std::memory_order_relaxed);
    if(pending_->retransmissions==1||
       (pending_->retransmissions&(pending_->retransmissions-1))==0){
      trace("RETRY seq="+std::to_string(pending_->sequence)+
        " ord="+std::to_string(pending_->ordinal)+
        " count="+std::to_string(pending_->retransmissions));
    }
  }
}

bool NetBridge::sendPacket(const Pending& packet){
  if(udp_==INVALID_SOCKET||packet.payload.size()>kMaxPayload||packet.expectedSize>kMaxPayload)return false;
  std::array<uint8_t,sizeof(Wire)+kFragmentPayload> datagram{};
  const uint32_t payloadSize=static_cast<uint32_t>(packet.payload.size());
  const uint32_t fragmentCount=payloadSize==0?1u:
    static_cast<uint32_t>((payloadSize+kFragmentPayload-1)/kFragmentPayload);
  const uint32_t payloadCrc=crc32(packet.payload.data(),packet.payload.size());
  for(uint32_t fragmentIndex=0;fragmentIndex<fragmentCount;++fragmentIndex){
    const uint32_t fragmentOffset=fragmentIndex*static_cast<uint32_t>(kFragmentPayload);
    const uint32_t fragmentSize=payloadSize==0?0u:static_cast<uint32_t>(
      std::min<size_t>(kFragmentPayload,payloadSize-fragmentOffset));
#ifdef TM3ONLINE_TESTING
    bool drop=false;
    const auto consumeDrop=[](std::atomic<uint32_t>& counter){
      uint32_t drops=counter.load(std::memory_order_acquire);
      while(drops!=0){
        if(counter.compare_exchange_weak(drops,drops-1,std::memory_order_acq_rel))return true;
      }
      return false;
    };
    drop=consumeDrop(testDrops_);
    if(!drop&&packet.replyTo==0)drop=consumeDrop(testRequestDrops_);
    if(!drop&&packet.replyTo!=0)drop=consumeDrop(testResponseDrops_);
    if(drop)continue;
#endif
    const Wire wire{kMagic,kProtocolVersion,packet.command,session_,packet.sequence,
      packet.replyTo,packet.ordinal,payloadSize,packet.expectedSize,packet.callSite,payloadCrc,
      fragmentOffset,fragmentSize};
    std::memcpy(datagram.data(),&wire,sizeof(wire));
    if(fragmentSize)std::memcpy(datagram.data()+sizeof(wire),
      packet.payload.data()+fragmentOffset,fragmentSize);
    const size_t size=sizeof(wire)+fragmentSize;
    const int sent=sendto(udp_,reinterpret_cast<const char*>(datagram.data()),static_cast<int>(size),0,
      reinterpret_cast<const sockaddr*>(&peerUdp_),sizeof(peerUdp_));
    if(sent!=static_cast<int>(size))return false;
    udpSent_.fetch_add(1,std::memory_order_relaxed);
  }
  return true;
}

bool NetBridge::sendAll(const void* data,size_t size){
  auto* bytes=static_cast<const char*>(data);
  while(size){
    const int sent=send(tcp_,bytes,static_cast<int>(std::min<size_t>(size,1u<<20)),0);
    if(sent<=0)return false;
    bytes+=sent;size-=static_cast<size_t>(sent);
  }
  return true;
}

bool NetBridge::recvAll(void* data,size_t size){
  auto* bytes=static_cast<char*>(data);
  while(size){
    const int received=recv(tcp_,bytes,static_cast<int>(std::min<size_t>(size,1u<<20)),0);
    if(received<=0)return false;
    bytes+=received;size-=static_cast<size_t>(received);
  }
  return true;
}

uint16_t NetBridge::readMailboxStatus(const Mailbox* mailbox){
  MemoryBarrier();
  const auto value=*reinterpret_cast<const volatile uint16_t*>(&mailbox->status);
  MemoryBarrier();
  return value;
}

void NetBridge::writeMailboxStatus(Mailbox* mailbox,uint16_t status){
  const bool capture=boundaryEnabled() && status==3 && mailbox->callSite==kGameplayBatchReturn && mailbox->command==kBatchTransfer;
  const uint32_t sequence=capture?mailbox->sequence:0;
  const uint64_t before=capture?boundaryQpc():0;
  MemoryBarrier();
  *reinterpret_cast<volatile uint16_t*>(&mailbox->status)=status;
  MemoryBarrier();
  if(capture){
    const uint64_t after=boundaryQpc();
    trace("LINK_PUBLISH seq="+std::to_string(sequence)+" before="+std::to_string(before)+" after="+std::to_string(after));
  }
}

void NetBridge::writeMailboxFlags(Mailbox* mailbox,uint16_t flags){
  MemoryBarrier();
  *reinterpret_cast<volatile uint16_t*>(&mailbox->flags)=flags;
  MemoryBarrier();
}

bool NetBridge::translateRamRange(size_t ramSize,uint32_t address,size_t size,size_t& offset){
  if(size==0){offset=0;return true;}
  const uint32_t segment=address&0xE0000000u;
  uint32_t physical=0;
  if(segment==0x80000000u||segment==0xA0000000u)physical=address&0x1FFFFFFFu;
  else if(address<ramSize)physical=address;
  else return false;
  offset=physical;
  return offset<=ramSize&&size<=ramSize-offset;
}

uint32_t NetBridge::crc32(const uint8_t* data,size_t size){
  uint32_t crc=~0u;
  for(size_t i=0;i<size;++i){
    crc^=data[i];
    for(int bit=0;bit<8;++bit)crc=(crc>>1)^(0xEDB88320u&-static_cast<int>(crc&1));
  }
  return ~crc;
}
