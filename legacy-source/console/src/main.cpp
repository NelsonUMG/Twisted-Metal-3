#include "core_host.hpp"
#include "video_buffer.hpp"
#include "console_ui.hpp"
#include "thread_schedule.hpp"
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
static std::atomic<bool> linkActive{false};
static ConsoleUI consoleUI(g);
static VideoBuffer videoBuffer;
static LRESULT CALLBACK WndProc(HWND h,UINT m,WPARAM w,LPARAM l){
  if(consoleUI.handle(h,m,w,l))return 0;
  switch(m){
  case WM_ACTIVATE:g.setInputEnabled(LOWORD(w)!=WA_INACTIVE);return 0;
  case WM_ENTERMENULOOP:g.setInputEnabled(false);return 0;
  case WM_EXITMENULOOP:g.setInputEnabled(GetForegroundWindow()==h);return 0;
  case WM_ERASEBKGND:return 1; // Background and video are composed off-screen.
  case WM_PAINT:{
    PAINTSTRUCT ps;HDC dc=BeginPaint(h,&ps);RECT r;GetClientRect(h,&r);
    if(HDC back=videoBuffer.prepare(dc,r.right,r.bottom)){
      FillRect(back,&r,(HBRUSH)GetStockObject(BLACK_BRUSH));
      if(linkActive.load()&&!g.net().connected()){
        SetBkMode(back,TRANSPARENT);SetTextColor(back,RGB(220,230,245));
        DrawTextW(back,L"Connecting to the other player... / Conectando con el otro jugador...",-1,&r,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
      }else if(g.loaded())g.paint(back,r);else consoleUI.paintHome(back,r);videoBuffer.present(dc);
    } // Allocation failure retains the previous image; never flashes black.
    EndPaint(h,&ps);return 0;
  }
  case WM_KEYDOWN:break;
  case WM_DESTROY:videoBuffer.reset();PostQuitMessage(0);return 0;
  }
  return DefWindowProc(h,m,w,l);
}
static std::vector<std::wstring> args(){int n=0;auto p=CommandLineToArgvW(GetCommandLineW(),&n);std::vector<std::wstring> v(p,p+n);LocalFree(p);return v;}
static std::string utf8(std::wstring_view value){if(value.empty())return {};const int size=WideCharToMultiByte(CP_UTF8,0,value.data(),static_cast<int>(value.size()),nullptr,0,nullptr,nullptr);std::string result(static_cast<size_t>(size),'\0');WideCharToMultiByte(CP_UTF8,0,value.data(),static_cast<int>(value.size()),result.data(),size,nullptr,nullptr);return result;}
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
  if(!std::filesystem::exists(game)&&std::filesystem::exists(base/L"game/TM3_SQRT_MERGE_V4.cue"))game=base/L"game/TM3_SQRT_MERGE_V4.cue";
  bool fullscreen=false,isHost=false,isClient=false,showSettings=false,empty=false;std::string saveSlot;
  std::filesystem::path sessionState;std::wstring returnEventName;DWORD parentPid=0;
  auto executableStem=executablePath.stem().wstring();
  for(auto& ch:executableStem)ch=static_cast<wchar_t>(std::towlower(ch));
  const bool aiProfileDiagnostic=executableStem.find(L"aiprofile")!=std::wstring::npos;
  const bool aiProfileV3Diagnostic=executableStem.find(L"aiprofilev3")!=std::wstring::npos;
  const bool rngCoreTraceDiagnostic=executableStem.find(L"rngcoretrace")!=std::wstring::npos;
  const bool rngCallerDiagnostic=executableStem.find(L"rngcaller")!=std::wstring::npos;
  const bool cosmeticRngV13=executableStem.find(L"v13")!=std::wstring::npos;
  const bool localRngV14=executableStem.find(L"v14")!=std::wstring::npos;
  const bool localRngV15=executableStem.find(L"v15")!=std::wstring::npos;
  const bool localRngV16=executableStem.find(L"v16")!=std::wstring::npos;
  if(aiProfileV3Diagnostic)core=base/L"cores/beetle_psx_aiprofile_v3.dll";
  else if(aiProfileDiagnostic)core=base/L"cores/beetle_psx_aiprofile.dll";
  else if(rngCoreTraceDiagnostic)core=base/L"cores/beetle_psx_rngcoretrace.dll";
  if(localRngV16)game=base/L"game_v16/TM3_LOCAL_RNG_V16.cue";
  else if(localRngV15)game=base/L"game_v15/TM3_LOCAL_RNG_V15.cue";
  else if(localRngV14)game=base/L"game_v14/TM3_LOCAL_RNG_V14.cue";
  else if(cosmeticRngV13)game=base/L"game_v13/TM3_COSMETIC_RNG_V13.cue";
  else if(rngCallerDiagnostic||aiProfileDiagnostic)game=base/L"game_rngcaller/TM3 RNGCaller.cue";
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
    else if(a[i]==L"--fullscreen")fullscreen=true;
    else if(a[i]==L"--show-settings")showSettings=true;
    else if(a[i]==L"--empty")empty=true;
    else if(a[i]==L"--session-state"&&i+1<a.size())sessionState=a[++i];
    else if(a[i]==L"--return-menu-event"&&i+1<a.size())returnEventName=a[++i];
    else if(a[i]==L"--parent-pid"&&i+1<a.size())parentPid=static_cast<DWORD>(std::stoul(a[++i]));
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
  linkActive.store(isHost||isClient);
  HANDLE parentHandle=parentPid?OpenProcess(SYNCHRONIZE,FALSE,parentPid):nullptr;
  HANDLE returnEvent=returnEventName.empty()?nullptr:OpenEventW(SYNCHRONIZE|EVENT_MODIFY_STATE,FALSE,returnEventName.c_str());
  const char* sessionReason="startup";
  const auto publishState=[&](const char* state){
    if(sessionState.empty())return;
    auto temporary=sessionState;temporary+=L".tmp";
    {std::ofstream out(temporary);out<<"{\"pid\":"<<GetCurrentProcessId()<<",\"state\":\""<<state<<"\",\"reason\":\""<<sessionReason<<"\",\"protocol\":7,\"player2_enabled\":"<<(g.secondController()?"true":"false")<<",\"transport_connected\":"<<(g.net().connected()?"true":"false")<<",\"guest_ready\":"<<(g.linkedReady()?"true":"false")<<",\"mailbox_magic\":"<<g.mailboxMagic()<<",\"menu\":"<<g.menuTable()<<",\"frames\":"<<g.videoGeneration()<<"}";if(!out)return;}
    MoveFileExW(temporary.c_str(),sessionState.c_str(),MOVEFILE_REPLACE_EXISTING);
  };
  publishState(linkActive.load()?"waiting":"local");
  tm3threads::setInstanceOffset(isHost?2u:isClient?4u:GetCurrentProcessId());
  tm3threads::Schedule presentationSchedule(tm3threads::Role::Presentation);
  g.setSaveSlot(saveSlot);
  if(empty)game.clear();
  if(!empty&&!g.load(core,game,base)){MessageBoxW(nullptr,L"Could not load the game. Check the image and BIOS in Settings.",L"TM3 Online",MB_ICONERROR);game.clear();g.disconnect();isHost=isClient=false;}

  WNDCLASSW wc{};wc.style=CS_DBLCLKS;wc.lpfnWndProc=WndProc;wc.hInstance=hi;wc.lpszClassName=L"TM3OnlineWindow";wc.hCursor=LoadCursor(nullptr,IDC_ARROW);RegisterClassW(&wc);
  const DWORD style=fullscreen?WS_POPUP:WS_OVERLAPPEDWINDOW;
  RECT r{0,0,fullscreen?1280:900,fullscreen?720:650};AdjustWindowRect(&r,style,TRUE);
  const std::wstring title=ConsoleUI::windowCaption(isHost||isClient,false,0);
  const int x=fullscreen?CW_USEDEFAULT:(isClient?940:20),y=fullscreen?CW_USEDEFAULT:40;
  HWND h=CreateWindowW(wc.lpszClassName,title.c_str(),style,x,y,r.right-r.left,r.bottom-r.top,nullptr,nullptr,hi,nullptr);
  consoleUI.attach(h,base,game,core,isHost||isClient);
  ShowWindow(h,fullscreen?SW_SHOWMAXIMIZED:SW_SHOWNORMAL);
  if(showSettings)consoleUI.openSettings(0);
  g.setInputEnabled(GetForegroundWindow()==h);
  LARGE_INTEGER frequency,titleCounter;QueryPerformanceFrequency(&frequency);QueryPerformanceCounter(&titleCounter);
  std::atomic<uint64_t> emulatedFrames{0},droppedClockFrames{0};
  const auto emulate=[&](std::stop_token stop){
    tm3threads::Schedule emulationSchedule(tm3threads::Role::Emulation);
    LARGE_INTEGER nowCounter,lastCounter;QueryPerformanceCounter(&lastCounter);
    double accumulator=0.0;
    while(!stop.stop_requested()){
      QueryPerformanceCounter(&nowCounter);
      double elapsed=static_cast<double>(nowCounter.QuadPart-lastCounter.QuadPart)/frequency.QuadPart;
      lastCounter=nowCounter;
      if(consoleUI.paused()||!g.loaded()||(linkActive.load()&&!g.net().connected())){accumulator=0;Sleep(1);continue;}
      const double step=1.0/std::max(1.0,g.fps());
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
  };
  std::jthread emulation(emulate);
  const auto changeGame=[&](std::filesystem::path next){
    const bool sameGame=next==game;
    emulation.request_stop();if(emulation.joinable())emulation.join();
    linkActive.store(false);
    g.disconnect();g.unload();isHost=isClient=false;game.clear();
    if(!next.empty()){
      const auto u8=next.lexically_normal().u8string();uint64_t hash=1469598103934665603ull;for(unsigned char c:u8){hash^=c;hash*=1099511628211ull;}
      std::ostringstream slot;slot<<"game_"<<std::hex<<hash;g.setSaveSlot(sameGame?saveSlot:slot.str());
      if(g.load(core,next,base))game=next;
      else MessageBoxW(h,consoleUI.english()?L"Could not load this game. Check the image and selected BIOS.":L"No se pudo cargar el juego. Revisa la imagen y la BIOS seleccionada.",L"TM3 Online",MB_ICONERROR);
    }
    consoleUI.contentChanged(game,false);SetWindowTextW(h,consoleUI.caption(0).c_str());
    emulation=std::jthread(emulate);
  };
  consoleUI.setGameAction([&](const std::filesystem::path& next){changeGame(next);publishState("local");});
  MSG msg{};LARGE_INTEGER nowCounter;
  uint64_t titleFrames=0;
  ULONGLONG nextTitleUpdate=0;
  uint64_t paintedGeneration=~uint64_t{0};
  const ULONGLONG connectionStart=GetTickCount64();bool linkConfirmed=false,returningMenu=false,returnedMenu=false;
  bool run=true;while(run){
    while(PeekMessage(&msg,nullptr,0,0,PM_REMOVE)){if(msg.message==WM_QUIT){run=false;break;}if(!consoleUI.translate(msg)){TranslateMessage(&msg);DispatchMessage(&msg);}}
    if(!run)break;
    g.setInputEnabled(GetForegroundWindow()==h);
    const ULONGLONG now=GetTickCount64();
    if(parentPid&&(!parentHandle||WaitForSingleObject(parentHandle,0)==WAIT_OBJECT_0)){PostMessageW(h,WM_CLOSE,0,0);parentPid=0;}
    if(linkActive.load()){
      const bool connected=g.net().connected();
      if(connected&&g.linkedReady()&&!linkConfirmed){linkConfirmed=true;publishState("connected");InvalidateRect(h,nullptr,FALSE);}
      const bool requested=returnEvent&&WaitForSingleObject(returnEvent,0)==WAIT_OBJECT_0;
      if(requested){ResetEvent(returnEvent);if(connected&&!returningMenu&&!returnedMenu)g.net().requestReturnToMenu();}
      const bool timedOut=!linkConfirmed&&now-connectionStart>20000;
      if(g.net().consumeReturnToMenu()&&connected&&!returningMenu){
        returningMenu=true;returnedMenu=false;sessionReason="explicit_menu_cancel";g.requestMainMenu();
      }
      if(returningMenu&&g.mainMenuReturned()){
        returningMenu=false;returnedMenu=true;publishState("returned");
      }
      if(returnedMenu&&g.menuTable()!=0x8007FEDC){returnedMenu=false;sessionReason="linked_menu_reentry";}
      if((requested&&!connected)||(linkConfirmed&&!connected)||timedOut||(returningMenu&&g.mainMenuReturnFailed())){
        sessionReason=timedOut?"connection_timeout":!connected?"peer_disconnected":"menu_return_fallback";
        // Reloading the same disc follows its normal boot into the main menu.
        // The emulation thread is joined before replacing the network bridge.
        const auto previousGame=game;changeGame(previousGame);
        publishState(timedOut?"failed":"returned");InvalidateRect(h,nullptr,FALSE);
      }
    }
    if(now>=nextTitleUpdate){
      if(linkActive.load())publishState(returnedMenu?"returned":returningMenu?"returning":linkConfirmed?"connected":"waiting");
      QueryPerformanceCounter(&nowCounter);
      const double titleSeconds=static_cast<double>(nowCounter.QuadPart-titleCounter.QuadPart)/frequency.QuadPart;
      const uint64_t currentFrames=emulatedFrames.load(std::memory_order_relaxed);
      const double measuredFps=titleSeconds>0.0?(currentFrames-titleFrames)/titleSeconds:0.0;
      const auto currentTitle=consoleUI.caption(measuredFps);
      SetWindowTextW(h,currentTitle.c_str());
      titleCounter=nowCounter;titleFrames=currentFrames;nextTitleUpdate=now+500;
    }
    const uint64_t generation=g.videoGeneration();
    if(generation!=paintedGeneration){InvalidateRect(h,nullptr,FALSE);paintedGeneration=generation;}
    Sleep(1);
  }
  emulation.request_stop();
  if(emulation.joinable())emulation.join();
  g.disconnect();g.unload();publishState("closed");
  if(parentHandle)CloseHandle(parentHandle);if(returnEvent)CloseHandle(returnEvent);return 0;
}
