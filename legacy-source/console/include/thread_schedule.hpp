#pragma once
#include <windows.h>
#include <avrt.h>
#include <algorithm>
#include <atomic>
#include <mutex>
#include <filesystem>
#include <fstream>
#include <vector>

namespace tm3threads {
enum class Role {Emulation=0,Presentation=1,Network=2};
struct Core {WORD group=0;KAFFINITY mask=0;};
inline std::atomic<unsigned> instanceOffset{0};
inline std::mutex profileMutex;
inline void setInstanceOffset(unsigned value){instanceOffset.store(value);}
inline std::vector<PROCESSOR_NUMBER> representatives(const std::vector<Core>& cores,WORD group,KAFFINITY allowed){
  std::vector<PROCESSOR_NUMBER> result;
  for(const auto& core:cores)if(core.group==group){const auto usable=core.mask&allowed;for(BYTE bit=0;bit<sizeof(KAFFINITY)*8;++bit)if(usable&(KAFFINITY{1}<<bit)){result.push_back({group,bit,0});break;}}
  return result;
}
inline std::vector<Core> topology(){
  DWORD bytes=0;GetLogicalProcessorInformationEx(RelationProcessorCore,nullptr,&bytes);if(!bytes)return {};
  std::vector<unsigned char> buffer(bytes);if(!GetLogicalProcessorInformationEx(RelationProcessorCore,reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(buffer.data()),&bytes))return {};
  std::vector<Core> result;
  for(DWORD offset=0;offset+sizeof(DWORD)*2<=bytes;){const auto* entry=reinterpret_cast<const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(buffer.data()+offset);if(!entry->Size||entry->Size>bytes-offset)break;if(entry->Relationship==RelationProcessorCore)for(WORD i=0;i<entry->Processor.GroupCount;++i)result.push_back({entry->Processor.GroupMask[i].Group,entry->Processor.GroupMask[i].Mask});offset+=entry->Size;}
  return result;
}
inline bool enabled(){wchar_t value[8]{};return !(GetEnvironmentVariableW(L"TM3O_CPU_SCHEDULING",value,8)>0&&value[0]==L'0');}
class Schedule {
public:
  explicit Schedule(Role role,unsigned offset=instanceOffset.load()){
    using Description=HRESULT(WINAPI*)(HANDLE,PCWSTR);
    if(auto describe=reinterpret_cast<Description>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"),"SetThreadDescription")))describe(GetCurrentThread(),role==Role::Emulation?L"TM3 Emulation":role==Role::Presentation?L"TM3 Presentation":L"TM3 Network");
    if(!enabled()){record(role,false);return;}
    GROUP_AFFINITY allowed{};
    // Do not implicitly move a thread between groups on large machines.
    if(GetActiveProcessorGroupCount()==1&&GetThreadGroupAffinity(GetCurrentThread(),&allowed)){
      DWORD_PTR processMask=0,systemMask=0;if(GetProcessAffinityMask(GetCurrentProcess(),&processMask,&systemMask))allowed.Mask&=processMask;
      const auto choices=representatives(topology(),allowed.Group,allowed.Mask);
      if(!choices.empty()){ideal_=choices[(offset+static_cast<unsigned>(role))%choices.size()];idealSet_=SetThreadIdealProcessorEx(GetCurrentThread(),&ideal_,&previousIdeal_)!=FALSE;}
    }
    if(role==Role::Emulation){
      library_=LoadLibraryExW(L"avrt.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
      if(library_){auto attach=reinterpret_cast<Attach>(GetProcAddress(library_,"AvSetMmThreadCharacteristicsW"));revert_=reinterpret_cast<Revert>(GetProcAddress(library_,"AvRevertMmThreadCharacteristics"));if(attach&&revert_){DWORD index=0;task_=attach(L"Games",&index);}}
      // No process-wide High/Realtime class, registry changes, hard affinity,
      // or priority increase for UI/network. Failure leaves normal scheduling.
    }
    record(role,true);
  }
  ~Schedule(){if(task_&&revert_)revert_(task_);if(idealSet_)SetThreadIdealProcessorEx(GetCurrentThread(),&previousIdeal_,nullptr);if(library_)FreeLibrary(library_);}
  Schedule(const Schedule&)=delete;Schedule& operator=(const Schedule&)=delete;
  bool idealApplied() const{return idealSet_;}
  bool multimediaApplied() const{return task_!=nullptr;}
  PROCESSOR_NUMBER ideal() const{return ideal_;}
private:
  void record(Role role,bool active) const{
    wchar_t target[32768]{};const auto length=GetEnvironmentVariableW(L"TM3O_THREAD_PROFILE_FILE",target,32768);if(!length||length>=32768)return;
    GROUP_AFFINITY affinity{};GetThreadGroupAffinity(GetCurrentThread(),&affinity);std::scoped_lock lock(profileMutex);std::ofstream output(std::filesystem::path(target),std::ios::app);if(!output)return;
    output<<"{\"thread_id\":"<<GetCurrentThreadId()<<",\"role\":\""<<(role==Role::Emulation?"emulation":role==Role::Presentation?"presentation":"network")<<"\",\"scheduling_enabled\":"<<(active?"true":"false")<<",\"group\":"<<affinity.Group<<",\"allowed_mask\":\""<<std::hex<<affinity.Mask<<std::dec<<"\",\"ideal_applied\":"<<(idealSet_?"true":"false")<<",\"preferred_cpu\":"<<static_cast<unsigned>(ideal_.Number)<<",\"mmcss_games\":"<<(task_?"true":"false")<<"}\n";
  }
  using Attach=HANDLE(WINAPI*)(LPCWSTR,LPDWORD);using Revert=BOOL(WINAPI*)(HANDLE);
  HMODULE library_{};HANDLE task_{};Revert revert_{};PROCESSOR_NUMBER ideal_{},previousIdeal_{};bool idealSet_=false;
};
}
