#include <windows.h>
#include <filesystem>
#include <set>
#include <string>
#include <iostream>
extern "C" __declspec(dllimport) UINT __stdcall ResolveInstallLocation(int,wchar_t*,UINT);
extern "C" __declspec(dllimport) UINT __stdcall ResolveSelectedFolder(const wchar_t*,wchar_t*,UINT);
int main(){
 std::set<std::wstring> paths;
 for(int index=0;index<6;++index){wchar_t path[32768]{};if(ResolveInstallLocation(index,path,32768)!=ERROR_SUCCESS)return 1;std::filesystem::path p(path);if(!p.is_absolute()||p.filename()!=L"TM3Online")return 2;paths.insert(path);}
 wchar_t small[2]{};if(ResolveInstallLocation(0,small,2)!=ERROR_INSUFFICIENT_BUFFER)return 3;
 if(ResolveInstallLocation(-1,small,2)!=ERROR_INVALID_PARAMETER||ResolveInstallLocation(6,small,2)!=ERROR_INVALID_PARAMETER)return 4;
 if(paths.size()!=6)return 5;
 for(auto input:{L"C:\\Users\\Prueba\\Escritorio",L"C:\\Users\\Prueba\\Música",L"D:\\Juegos\\TM3Online",L"D:\\Juegos\\TM3Online\\",L"D:\\"}){
  wchar_t output[32768]{};if(ResolveSelectedFolder(input,output,32768)!=ERROR_SUCCESS)return 6;
  std::filesystem::path path(output);if(path.filename()!=L"TM3Online"||path.parent_path().filename()==L"TM3Online")return 7;
 }
 if(ResolveSelectedFolder(L"relative",small,2)!=ERROR_INVALID_PARAMETER)return 8;
 std::cout<<"PASS: Desktop known-folder resolution, six shell locations, Unicode, arbitrary selected folders, no duplicate TM3Online, root drive, invalid input and buffers.\n";return 0;
}
