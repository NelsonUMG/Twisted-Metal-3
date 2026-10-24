#include <windows.h>
#include <commctrl.h>
#include <objbase.h>
#include <shellapi.h>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <array>
#include <stdexcept>
#pragma comment(linker,"/manifestdependency:\"type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")
#pragma pack(push,1)
struct Footer {char magic[8];unsigned long long msiOffset,msiSize,mstOffset,mstSize;unsigned char msiHash[32],mstHash[32];};
#pragma pack(pop)
static_assert(sizeof(Footer)==104);
namespace fs=std::filesystem;
static void require(bool good){if(!good)throw std::runtime_error("Invalid or damaged installer / Instalador incompleto o dañado");}
static void extract(std::ifstream& input,unsigned long long offset,unsigned long long size,const unsigned char* expected,const fs::path& target){
 BCRYPT_ALG_HANDLE algorithm{};BCRYPT_HASH_HANDLE hash{};
 require(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0);
 require(BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)>=0);
 std::ofstream output(target,std::ios::binary|std::ios::trunc);require(bool(output));input.clear();input.seekg(offset);
 std::vector<char> buffer(1048576);
 while(size){auto count=static_cast<size_t>(size<buffer.size()?size:buffer.size());input.read(buffer.data(),count);require(static_cast<size_t>(input.gcount())==count);output.write(buffer.data(),count);require(bool(output));require(BCryptHashData(hash,reinterpret_cast<PUCHAR>(buffer.data()),static_cast<ULONG>(count),0)>=0);size-=count;}
 unsigned char actual[32]{};require(BCryptFinishHash(hash,actual,32,0)>=0);BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(algorithm,0);output.close();require(memcmp(actual,expected,32)==0);
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int){
 bool english=false,extractOnly=false;fs::path output;
 try{
  int argc{};auto argv=CommandLineToArgvW(GetCommandLineW(),&argc);
  for(int i=1;i<argc;++i){std::wstring arg=argv[i];if(arg==L"--extract-only")extractOnly=true;else if(arg==L"--lang=en")english=true;else if(arg==L"--lang=es")english=false;else if(arg==L"--output"&&i+1<argc)output=argv[++i];else{LocalFree(argv);throw std::runtime_error("Invalid arguments");}}
  LocalFree(argv);
  if(!extractOnly){
   TASKDIALOG_BUTTON buttons[]={{100,L"Español"},{101,L"English"}};
   TASKDIALOGCONFIG dialog{};dialog.cbSize=sizeof(dialog);dialog.dwFlags=TDF_USE_COMMAND_LINKS|TDF_ALLOW_DIALOG_CANCELLATION;dialog.dwCommonButtons=TDCBF_CANCEL_BUTTON;dialog.pszWindowTitle=L"TM3 Online Setup";dialog.pszMainInstruction=L"Elige el idioma / Choose your language";dialog.cButtons=2;dialog.pButtons=buttons;dialog.nDefaultButton=PRIMARYLANGID(GetUserDefaultUILanguage())==LANG_SPANISH?100:101;
   int selected{};require(SUCCEEDED(TaskDialogIndirect(&dialog,&selected,nullptr,nullptr)));if(selected!=100&&selected!=101)return 1602;english=selected==101;
  }
  wchar_t executable[32768]{};require(GetModuleFileNameW(nullptr,executable,32768)>0);
  std::ifstream input(fs::path(executable),std::ios::binary);require(bool(input));input.seekg(0,std::ios::end);auto length=static_cast<unsigned long long>(input.tellg());require(length>sizeof(Footer));input.seekg(length-sizeof(Footer));Footer footer{};input.read(reinterpret_cast<char*>(&footer),sizeof(footer));require(memcmp(footer.magic,"TM3SET01",8)==0);
  require(footer.msiOffset<length&&footer.msiSize<=length-footer.msiOffset&&footer.mstOffset==footer.msiOffset+footer.msiSize&&footer.mstSize<=length-footer.mstOffset&&footer.mstOffset+footer.mstSize==length-sizeof(Footer));
  fs::path tempRoot;
  if(extractOnly){require(!output.empty());require(!fs::exists(output));fs::create_directories(output);}
  else{wchar_t temporary[32768]{};require(GetTempPathW(32768,temporary)>0);tempRoot=fs::path(temporary);GUID guid{};require(SUCCEEDED(CoCreateGuid(&guid)));wchar_t text[40]{};StringFromGUID2(guid,text,40);output=tempRoot/(L"TM3Setup-"+std::wstring(text));require(fs::create_directory(output));}
  SetCursor(LoadCursor(nullptr,IDC_WAIT));
  extract(input,footer.msiOffset,footer.msiSize,footer.msiHash,output/L"TM3Online.msi");
  if(english)extract(input,footer.mstOffset,footer.mstSize,footer.mstHash,output/L"English.mst");
  SetCursor(LoadCursor(nullptr,IDC_ARROW));
  if(extractOnly)return 0;
  wchar_t system[32768]{};require(GetSystemDirectoryW(system,32768)>0);auto msiexec=fs::path(system)/L"msiexec.exe";
  std::wstring command=L"\""+msiexec.wstring()+L"\" /i \""+(output/L"TM3Online.msi").wstring()+L"\" /norestart";
  if(english)command+=L" TRANSFORMS=\""+(output/L"English.mst").wstring()+L"\" TRANSFORMSSECURE=1";
  STARTUPINFOW start{};start.cb=sizeof(start);PROCESS_INFORMATION process{};require(CreateProcessW(msiexec.c_str(),command.data(),nullptr,nullptr,FALSE,0,nullptr,nullptr,&start,&process)!=FALSE);CloseHandle(process.hThread);WaitForSingleObject(process.hProcess,INFINITE);DWORD result{};GetExitCodeProcess(process.hProcess,&result);CloseHandle(process.hProcess);
  // This directory was just created by this process, beneath the Windows temp folder.
  if(fs::equivalent(output.parent_path(),tempRoot)&&output.filename().wstring().rfind(L"TM3Setup-",0)==0){std::error_code ignored;fs::remove_all(output,ignored);}
  return static_cast<int>(result);
 }catch(const std::exception&){if(!extractOnly)MessageBoxW(nullptr,english?L"The installer is incomplete or could not start. Copy it again and retry.":L"El instalador está incompleto o no pudo iniciar. Cópialo de nuevo e inténtalo otra vez.",L"TM3 Online Setup",MB_OK|MB_ICONERROR);return 1;}
}
