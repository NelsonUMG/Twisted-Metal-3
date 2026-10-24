#include <windows.h>
#include <filesystem>
#include <set>
#include <string>
#include <iostream>
extern "C" __declspec(dllimport) UINT __stdcall ResolveInstallLocation(int,wchar_t*,UINT);
int main(){std::set<std::wstring> paths;for(int index=0;index<6;++index){wchar_t path[32768]{};if(ResolveInstallLocation(index,path,32768)!=ERROR_SUCCESS)return 1;std::filesystem::path destination(path);if(!destination.is_absolute()||destination.filename()!=L"TM3Online")return 2;paths.insert(path);}wchar_t small[2]{};if(ResolveInstallLocation(0,small,2)!=ERROR_INSUFFICIENT_BUFFER)return 3;if(ResolveInstallLocation(-1,small,2)!=ERROR_INVALID_PARAMETER)return 4;if(ResolveInstallLocation(6,small,2)!=ERROR_INVALID_PARAMETER)return 5;if(paths.size()!=6)return 6;std::cout<<"PASS: six known-folder destinations, absolute Unicode paths, TM3Online subfolder, invalid index and buffer guards.\n";return 0;}
