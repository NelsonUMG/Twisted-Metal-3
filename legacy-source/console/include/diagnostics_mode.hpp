#pragma once
#include <windows.h>
// Distribution default: no automatic captures. Synchronization stays enabled.
inline bool tm3DiagnosticsEnabled(){
  static const bool enabled=[](){wchar_t value[8]{};return GetEnvironmentVariableW(L"TM3O_DIAGNOSTICS",value,8)==1&&value[0]==L'1';}();
  return enabled;
}
