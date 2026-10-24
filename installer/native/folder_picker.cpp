#include <windows.h>
#include <msi.h>
#include <msiquery.h>
#include <shlobj.h>
#include <filesystem>
#include <string>
#include <array>

namespace {
const std::array<const KNOWNFOLDERID*,6> folders={&FOLDERID_Desktop,&FOLDERID_Downloads,&FOLDERID_Documents,&FOLDERID_Music,&FOLDERID_Pictures,&FOLDERID_Videos};
std::wstring destination(const wchar_t* folder){
 if(!folder||!*folder)return {};
 std::filesystem::path path(folder);
 if(!path.is_absolute())return {};
 path=path.lexically_normal();
 while(!path.has_filename()&&path.has_relative_path())path=path.parent_path();
 if(_wcsicmp(path.filename().c_str(),L"TM3Online")!=0)path/=L"TM3Online";
 return path.wstring();
}
std::wstring knownDestination(int index){
 if(index<0||index>=static_cast<int>(folders.size()))return {};
 PWSTR folder=nullptr;
 if(FAILED(SHGetKnownFolderPath(*folders[index],KF_FLAG_DONT_VERIFY,nullptr,&folder)))return {};
 auto result=destination(folder);CoTaskMemFree(folder);return result;
}
int CALLBACK browseCallback(HWND dialog,UINT message,LPARAM selection,LPARAM){
 if(message==BFFM_INITIALIZED){
  PWSTR desktop=nullptr;
  if(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_Desktop,KF_FLAG_DONT_VERIFY,nullptr,&desktop))){
   SendMessageW(dialog,BFFM_SETSELECTIONW,TRUE,reinterpret_cast<LPARAM>(desktop));CoTaskMemFree(desktop);
  }
 }else if(message==BFFM_SELCHANGED){
  wchar_t folder[32768]{};
  bool valid=SHGetPathFromIDListEx(reinterpret_cast<PCIDLIST_ABSOLUTE>(selection),folder,32768,GPFIDL_DEFAULT)!=FALSE;
  SendMessageW(dialog,BFFM_ENABLEOK,0,valid);
 }
 return 0;
}
std::wstring choose(HWND owner,bool english){
 HRESULT initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
 wchar_t display[MAX_PATH]{};BROWSEINFOW browse{};
 browse.hwndOwner=owner;
 // NULL is the virtual Desktop root, with an expandable shell folder tree.
 browse.pidlRoot=nullptr; browse.pszDisplayName=display;
 browse.lpszTitle=english?L"Select a folder. TM3Online will be created inside it.":L"Selecciona una carpeta. Se creará TM3Online dentro de ella.";
 browse.ulFlags=BIF_RETURNONLYFSDIRS; // Compact classic tree, not Explorer or a list of locations.
 browse.lpfn=browseCallback;
 PIDLIST_ABSOLUTE selected=SHBrowseForFolderW(&browse);
 std::wstring result;
 if(selected){wchar_t folder[32768]{};if(SHGetPathFromIDListEx(selected,folder,32768,GPFIDL_DEFAULT))result=destination(folder);CoTaskMemFree(selected);}
 if(SUCCEEDED(initialized))CoUninitialize();
 return result;
}
UINT copyResult(const std::wstring& path,wchar_t* output,UINT capacity){
 if(path.empty())return ERROR_INVALID_PARAMETER;
 if(!output||capacity<=path.size())return ERROR_INSUFFICIENT_BUFFER;
 wcscpy_s(output,capacity,path.c_str());return ERROR_SUCCESS;
}
}
extern "C" __declspec(dllexport) UINT __stdcall PickInstallFolder(MSIHANDLE install){
 try{wchar_t language[16]{};DWORD size=16;MsiGetPropertyW(install,L"ProductLanguage",language,&size);auto result=choose(GetForegroundWindow(),wcscmp(language,L"1033")==0);return result.empty()?ERROR_SUCCESS:MsiSetPropertyW(install,L"INSTALLFOLDER",result.c_str());}
 catch(...){return ERROR_INSTALL_FAILURE;}
}
extern "C" __declspec(dllexport) UINT __stdcall ResolveInstallLocation(int index,wchar_t* output,UINT capacity){return copyResult(knownDestination(index),output,capacity);}
extern "C" __declspec(dllexport) UINT __stdcall ResolveSelectedFolder(const wchar_t* folder,wchar_t* output,UINT capacity){return copyResult(destination(folder),output,capacity);}
