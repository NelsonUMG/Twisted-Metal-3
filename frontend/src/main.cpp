#include "core_host.hpp"
#include <windows.h>
#include <shellapi.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <filesystem>
#include <cctype>
#include <cwctype>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

static CoreHost g;
static LRESULT CALLBACK WndProc(HWND h,UINT m,WPARAM w,LPARAM l){switch(m){case WM_ACTIVATE:g.setInputEnabled(LOWORD(w)!=WA_INACTIVE);return 0;case WM_PAINT:{PAINTSTRUCT ps;HDC dc=BeginPaint(h,&ps);RECT r;GetClientRect(h,&r);FillRect(dc,&r,(HBRUSH)GetStockObject(BLACK_BRUSH));g.paint(dc,r);EndPaint(h,&ps);return 0;}case WM_KEYDOWN:if(w==VK_ESCAPE){PostQuitMessage(0);return 0;}break;case WM_DESTROY:PostQuitMessage(0);return 0;}return DefWindowProc(h,m,w,l);}
static std::vector<std::wstring> args(){int n=0;auto p=CommandLineToArgvW(GetCommandLineW(),&n);std::vector<std::wstring> v(p,p+n);LocalFree(p);return v;}
static std::string utf8(std::wstring_view value){if(value.empty())return {};const int size=WideCharToMultiByte(CP_UTF8,0,value.data(),static_cast<int>(value.size()),nullptr,0,nullptr,nullptr);std::string result(static_cast<size_t>(size),'\0');WideCharToMultiByte(CP_UTF8,0,value.data(),static_cast<int>(value.size()),result.data(),size,nullptr,nullptr);return result;}
static std::wstring wide(std::string_view value){if(value.empty())return {};const int size=MultiByteToWideChar(CP_UTF8,0,value.data(),static_cast<int>(value.size()),nullptr,0);std::wstring result(static_cast<size_t>(size),L'\0');MultiByteToWideChar(CP_UTF8,0,value.data(),static_cast<int>(value.size()),result.data(),size);return result;}
static bool endpointFromFile(const std::filesystem::path& path,std::string& host,uint16_t& port){
  std::ifstream input(path);
  std::string endpoint;
  if(!input||!std::getline(input,endpoint))return true;
  if(endpoint.size()>=3&&static_cast<unsigned char>(endpoint[0])==0xEF&&
     static_cast<unsigned char>(endpoint[1])==0xBB&&static_cast<unsigned char>(endpoint[2])==0xBF)endpoint.erase(0,3);
  while(!endpoint.empty()&&std::isspace(static_cast<unsigned char>(endpoint.front())))endpoint.erase(endpoint.begin());
  while(!endpoint.empty()&&std::isspace(static_cast<unsigned char>(endpoint.back())))endpoint.pop_back();
  if(endpoint.empty()||endpoint.front()=='#')return true;
  const auto separator=endpoint.rfind(':');
  if(separator==std::string::npos||separator==0||separator+1>=endpoint.size())return false;
  try{
    const auto parsedPort=std::stoul(endpoint.substr(separator+1));
    if(parsedPort==0||parsedPort>0xFFFFu)return false;
    host=endpoint.substr(0,separator);port=static_cast<uint16_t>(parsedPort);return true;
  }catch(...){return false;}
}

int WINAPI wWinMain(HINSTANCE hi,HINSTANCE,LPWSTR,int){
  auto a=args();std::array<wchar_t,32768> modulePath{};const DWORD moduleLength=GetModuleFileNameW(nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  const auto executablePath=moduleLength?std::filesystem::path(std::wstring(modulePath.data(),moduleLength)):std::filesystem::path(a[0]);
  auto base=executablePath.parent_path();auto core=base/L"cores/beetle_psx_libretro.dll";auto game=base/L"game/TM3 Online.cue";
  bool fullscreen=true,isHost=false,isClient=false;std::string saveSlot;
  auto executableStem=executablePath.stem().wstring();
  for(auto& ch:executableStem)ch=static_cast<wchar_t>(std::towlower(ch));
  if(executableStem.find(L"oscar")!=std::wstring::npos){
    isHost=true;fullscreen=false;saveSlot="oscar";
    if(!g.net().host(27888)){MessageBoxW(nullptr,L"No se pudo iniciar a Oscar en TCP/UDP 27888.",L"TM3 Online",MB_ICONERROR);return 2;}
  }else if(executableStem.find(L"sofia")!=std::wstring::npos){
    isClient=true;fullscreen=false;saveSlot="sofia";
    std::string server="127.0.0.1";uint16_t serverPort=27888;
    if(!endpointFromFile(base/L"TM3Online_Server.txt",server,serverPort)){
      MessageBoxW(nullptr,L"TM3Online_Server.txt debe contener IP:PUERTO, por ejemplo 127.0.0.1:27888.",L"TM3 Online",MB_ICONERROR);return 2;
    }
    if(!g.net().join(server,serverPort)){MessageBoxW(nullptr,L"No se pudo conectar a Sofia con Oscar.",L"TM3 Online",MB_ICONERROR);return 2;}
  }
  for(size_t i=1;i<a.size();i++){
    if(a[i]==L"--core"&&i+1<a.size())core=a[++i];
    else if(a[i]==L"--game"&&i+1<a.size())game=a[++i];
    else if(a[i]==L"--windowed")fullscreen=false;
    else if(a[i]==L"--save-slot"&&i+1<a.size()){saveSlot=utf8(a[++i]);for(char& ch:saveSlot)if(!std::isalnum(static_cast<unsigned char>(ch))&&ch!='-'&&ch!='_')ch='_';}
    else if(a[i]==L"--host"&&i+1<a.size()){
      if(isHost||isClient){MessageBoxW(nullptr,L"El modo de transporte se especifico dos veces.",L"TM3 Online",MB_ICONERROR);return 2;}
      isHost=true;const auto port=static_cast<uint16_t>(std::stoi(a[++i]));
      if(!g.net().host(port)){MessageBoxW(nullptr,L"No se pudo iniciar el host TCP/UDP.",L"TM3 Online",MB_ICONERROR);return 2;}
    }else if(a[i]==L"--join"&&i+1<a.size()){
      if(isHost||isClient){MessageBoxW(nullptr,L"El modo de transporte se especifico dos veces.",L"TM3 Online",MB_ICONERROR);return 2;}
      isClient=true;auto endpoint=a[++i];const auto separator=endpoint.rfind(L':');
      if(separator==std::wstring::npos){MessageBoxW(nullptr,L"Usa --join HOST:PUERTO.",L"TM3 Online",MB_ICONERROR);return 2;}
      const std::string host=utf8(std::wstring_view(endpoint).substr(0,separator));
      const auto port=static_cast<uint16_t>(std::stoi(endpoint.substr(separator+1)));
      if(!g.net().join(host,port)){MessageBoxW(nullptr,L"No se pudo iniciar el cliente TCP/UDP.",L"TM3 Online",MB_ICONERROR);return 2;}
    }
  }
  if(saveSlot.empty()){if(isHost)saveSlot="host";else if(isClient)saveSlot="client";}
  g.setSaveSlot(saveSlot);
  if(!g.load(core,game,base)){MessageBoxW(nullptr,L"No se pudo cargar el core o el juego. Revisa las rutas.",L"TM3 Online",MB_ICONERROR);return 1;}

  WNDCLASSW wc{};wc.lpfnWndProc=WndProc;wc.hInstance=hi;wc.lpszClassName=L"TM3OnlineWindow";wc.hCursor=LoadCursor(nullptr,IDC_ARROW);RegisterClassW(&wc);
  const DWORD style=fullscreen?WS_POPUP:WS_OVERLAPPEDWINDOW;
  RECT r{0,0,fullscreen?1280:900,fullscreen?720:650};AdjustWindowRect(&r,style,FALSE);
  const std::wstring title=isHost?L"TM3 OSCAR - SERVIDOR TCP":isClient?L"TM3 SOFIA - CLIENTE TCP":L"Twisted Metal III Online";
  const int x=fullscreen?CW_USEDEFAULT:(isClient?940:20),y=fullscreen?CW_USEDEFAULT:40;
  HWND h=CreateWindowW(wc.lpszClassName,title.c_str(),style,x,y,r.right-r.left,r.bottom-r.top,nullptr,nullptr,hi,nullptr);
  ShowWindow(h,fullscreen?SW_SHOWMAXIMIZED:SW_SHOWNORMAL);
  g.setInputEnabled(GetForegroundWindow()==h);
  LARGE_INTEGER frequency,titleCounter;QueryPerformanceFrequency(&frequency);QueryPerformanceCounter(&titleCounter);
  const double step=1.0/g.fps();
  std::atomic<uint64_t> emulatedFrames{0},droppedClockFrames{0};
  std::jthread emulation([&](std::stop_token stop){
    LARGE_INTEGER nowCounter,lastCounter;QueryPerformanceCounter(&lastCounter);
    double accumulator=0.0;
    while(!stop.stop_requested()){
      QueryPerformanceCounter(&nowCounter);
      double elapsed=static_cast<double>(nowCounter.QuadPart-lastCounter.QuadPart)/frequency.QuadPart;
      lastCounter=nowCounter;
      elapsed=std::clamp(elapsed,0.0,0.25);
      accumulator+=elapsed;
      if(accumulator>=step){
        // Recupera retrasos breves para que las dos PS1 vuelvan al mismo
        // cuadro, pero limita una pausa larga a 100 ms de trabajo. Este hilo
        // no se detiene durante WM_ENTERSIZEMOVE al maximizar/redimensionar.
        constexpr uint64_t kMaxCatchUpFrames=6;
        const auto dueFrames=static_cast<uint64_t>(accumulator/step);
        const auto framesToRun=std::min(dueFrames,kMaxCatchUpFrames);
        if(dueFrames>kMaxCatchUpFrames){
          const auto trimmedFrames=dueFrames-kMaxCatchUpFrames;
          droppedClockFrames.fetch_add(trimmedFrames,std::memory_order_relaxed);
          accumulator-=static_cast<double>(trimmedFrames)*step;
        }
        for(uint64_t frame=0;frame<framesToRun;++frame){
          g.runFrame();emulatedFrames.fetch_add(1,std::memory_order_relaxed);accumulator-=step;
        }
      }
      Sleep(1);
    }
  });
  MSG msg{};LARGE_INTEGER nowCounter;
  uint64_t titleFrames=0;
  ULONGLONG nextTitleUpdate=0;
  bool run=true;while(run){
    while(PeekMessage(&msg,nullptr,0,0,PM_REMOVE)){if(msg.message==WM_QUIT){run=false;break;}TranslateMessage(&msg);DispatchMessage(&msg);}
    if(!run)break;
    g.setInputEnabled(GetForegroundWindow()==h);
    const ULONGLONG now=GetTickCount64();
    if(now>=nextTitleUpdate){
      QueryPerformanceCounter(&nowCounter);
      const double titleSeconds=static_cast<double>(nowCounter.QuadPart-titleCounter.QuadPart)/frequency.QuadPart;
      const uint64_t currentFrames=emulatedFrames.load(std::memory_order_relaxed);
      const double measuredFps=titleSeconds>0.0?(currentFrames-titleFrames)/titleSeconds:0.0;
      std::wostringstream performance;
      performance<<std::fixed<<std::setprecision(1)<<L" | fps="<<measuredFps
        <<L" clock-drop="<<droppedClockFrames.load(std::memory_order_relaxed)
        <<L" audio-drop="<<g.droppedAudioFrames();
      const auto currentTitle=title+L" | "+wide(g.net().status())+performance.str();
      SetWindowTextW(h,currentTitle.c_str());
      titleCounter=nowCounter;titleFrames=currentFrames;nextTitleUpdate=now+500;
    }
    InvalidateRect(h,nullptr,FALSE);Sleep(1);
  }
  emulation.request_stop();
  if(emulation.joinable())emulation.join();
  g.unload();return 0;
}
