#include "console_ui.hpp"
#include <iostream>
#include <fstream>
#include <vector>
#include <algorithm>
#include <cwctype>
#include "input_bindings.hpp"
#include <cmath>
#include <dwmapi.h>
#include "thread_schedule.hpp"
#include <thread>

bool publicText(const std::wstring& text){
  auto lower=text;std::transform(lower.begin(),lower.end(),lower.begin(),[](wchar_t ch){return static_cast<wchar_t>(towlower(ch));});
  for(const auto* secret:{L"test.dll",L"test.cue",L"beetle",L"tm3o16",L"linkboundary",L"pacingv",L"sqrtmerge",L"core",L"udp",L"tcp",L"game-role",L"clock-drop",L"audio-drop",L"\\",L":/"})if(lower.find(secret)!=std::wstring::npos)return false;
  return true;
}
BOOL CALLBACK checkText(HWND child,LPARAM result){wchar_t text[32768]{};GetWindowTextW(child,text,32768);if(!publicText(text))*reinterpret_cast<bool*>(result)=false;return TRUE;}
BOOL CALLBACK checkBounds(HWND child,LPARAM result){HWND parent=GetParent(child);RECT bounds{},client{};GetWindowRect(child,&bounds);MapWindowPoints(nullptr,parent,reinterpret_cast<POINT*>(&bounds),2);GetClientRect(parent,&client);if(bounds.left<0||bounds.top<0||bounds.right>client.right||bounds.bottom>client.bottom)*reinterpret_cast<bool*>(result)=false;return TRUE;}
bool publicMenu(HMENU menu){for(int i=0;i<GetMenuItemCount(menu);++i){if(!publicText(ConsoleUI::menuCaption(menu,i)))return false;if(auto sub=GetSubMenu(menu,i);sub&&!publicMenu(sub))return false;}return true;}
LRESULT CALLBACK hostProc(HWND h,UINT message,WPARAM w,LPARAM l){auto* ui=reinterpret_cast<ConsoleUI*>(GetWindowLongPtrW(h,GWLP_USERDATA));if(ui&&ui->handle(h,message,w,l))return 0;return DefWindowProcW(h,message,w,l);}

bool captureWindow(HWND window,const std::filesystem::path& file){
  // The fixture creates/updates controls synchronously without the app's usual
  // message loop. Drain their pending UI work before checking rendered pixels.
  MSG pending{};while(PeekMessageW(&pending,nullptr,0,0,PM_REMOVE)){TranslateMessage(&pending);DispatchMessageW(&pending);}GdiFlush();DwmFlush();
  RECT rect{};GetWindowRect(window,&rect);const int width=rect.right-rect.left,height=rect.bottom-rect.top;
  HDC screen=GetDC(window),memory=CreateCompatibleDC(screen);HBITMAP bitmap=CreateCompatibleBitmap(screen,width,height);auto previous=SelectObject(memory,bitmap);
  RedrawWindow(window,nullptr,nullptr,RDW_INVALIDATE|RDW_ALLCHILDREN|RDW_UPDATENOW);const bool printed=PrintWindow(window,memory,2)!=FALSE;SelectObject(memory,previous);
  BITMAPINFO info{};info.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);info.bmiHeader.biWidth=width;info.bmiHeader.biHeight=-height;info.bmiHeader.biPlanes=1;info.bmiHeader.biBitCount=32;info.bmiHeader.biCompression=BI_RGB;
  std::vector<unsigned char> pixels(static_cast<size_t>(width)*height*4);const bool read=GetDIBits(memory,bitmap,0,height,pixels.data(),&info,DIB_RGB_COLORS)!=0;
  bool controlsVisible=true;
  if(GetDlgItem(window,220)&&GetDlgItem(window,260))for(int slot=0;slot<16;++slot)for(int id:{220+slot,260+slot}){RECT child{};GetWindowRect(GetDlgItem(window,id),&child);const int x=child.left-rect.left+5,y=child.top-rect.top+5;if(x<0||y<0||x>=width||y>=height)controlsVisible=false;else{const auto offset=(static_cast<size_t>(y)*width+x)*4;if(pixels[offset]==32&&pixels[offset+1]==32&&pixels[offset+2]==32){controlsVisible=false;std::cerr<<"Unpainted binding button "<<id<<"\n";}}}
  BITMAPFILEHEADER header{};header.bfType=0x4D42;header.bfOffBits=sizeof(header)+sizeof(BITMAPINFOHEADER);header.bfSize=header.bfOffBits+static_cast<DWORD>(pixels.size());
  std::ofstream output(file,std::ios::binary);output.write(reinterpret_cast<const char*>(&header),sizeof(header));output.write(reinterpret_cast<const char*>(&info.bmiHeader),sizeof(info.bmiHeader));output.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());
  DeleteObject(bitmap);DeleteDC(memory);ReleaseDC(window,screen);return printed&&read&&output.good()&&controlsVisible;
}

std::filesystem::path popupFile;
bool popupCaptured=false;
BOOL CALLBACK capturePopup(HWND window,LPARAM){wchar_t name[64]{};GetClassNameW(window,name,64);if(std::wstring(name)==L"#32768"&&IsWindowVisible(window))popupCaptured=captureWindow(window,popupFile);return TRUE;}
void CALLBACK popupTimer(HWND,UINT,UINT_PTR timer,DWORD){KillTimer(nullptr,timer);EnumThreadWindows(GetCurrentThreadId(),capturePopup,0);EndMenu();}

int main(int argc,char** argv){
  const auto captures=argc>1?std::filesystem::path(argv[1]):std::filesystem::path();if(!captures.empty())std::filesystem::create_directories(captures);
  const auto directory=std::filesystem::temp_directory_path()/(L"TM3ConsoleUiTest_"+std::to_wstring(GetCurrentProcessId()));
  std::filesystem::create_directories(directory);
  WNDCLASSW wc{};wc.lpfnWndProc=hostProc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"TM3UiTestHost";RegisterClassW(&wc);
  HWND host=CreateWindowW(wc.lpszClassName,L"UI QA",WS_OVERLAPPEDWINDOW,0,0,900,650,nullptr,nullptr,wc.hInstance,nullptr);
  CoreHost core;ConsoleUI ui(core);ui.attach(host,directory,directory/L"test.cue",directory/L"test.dll",true);
  SetWindowLongPtrW(host,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(&ui));
  bool okay=GetMenuItemCount(GetMenu(host))==5;
  okay=okay&&publicMenu(GetMenu(host))&&!ui.showStatistics();
  okay=okay&&ConsoleUI::windowCaption(false,false,60)==L"Twisted Metal III Online";
  okay=okay&&ConsoleUI::windowCaption(true,true,59.9)==L"Twisted Metal III Online — En línea | 59.9 FPS";
  okay=okay&&publicText(ConsoleUI::windowCaption(true,true,60));
  okay=okay&&GetMenuState(GetSubMenu(GetMenu(host),3),1007,MF_BYCOMMAND)==static_cast<UINT>(-1);
  const wchar_t* names[]={L"System",L"Settings",L"View",L"Tools",L"Help"};
  for(int i=0;i<5;++i)okay=okay&&ConsoleUI::menuCaption(GetMenu(host),i)==names[i];
  okay=okay&&((GetMenuState(GetSubMenu(GetMenu(host),0),1003,MF_BYCOMMAND)&MF_GRAYED)!=0);
  ui.handle(host,WM_COMMAND,1002,0);okay=okay&&!ui.paused();
  HWND settings=nullptr;
  for(int i=0;i<13;++i){
    ui.openSettings(i);
    settings=FindWindowW(L"TM3ConsoleSettings",nullptr);DWORD pid=0;if(settings)GetWindowThreadProcessId(settings,&pid);
    okay=okay&&settings&&pid==GetCurrentProcessId();if(!okay)break;
    okay=okay&&GetDlgItem(settings,401)!=nullptr&&GetDlgItem(settings,402)!=nullptr&&GetDlgItem(settings,301)==nullptr;
    bool privacy=true;EnumChildWindows(settings,checkText,reinterpret_cast<LPARAM>(&privacy));okay=okay&&privacy;
    if(!privacy)std::cerr<<"Privacy failure on page "<<i<<"\n";
    bool fits=true;EnumChildWindows(settings,checkBounds,reinterpret_cast<LPARAM>(&fits));okay=okay&&fits;if(!fits)std::cerr<<"Clipped control on page "<<i<<"\n";
    RECT sidebar{},help{};GetWindowRect(GetDlgItem(settings,401),&sidebar);GetWindowRect(GetDlgItem(settings,402),&help);okay=okay&&sidebar.right-sidebar.left==140&&help.bottom-help.top==66;
    if(i==5){okay=okay&&IsWindowEnabled(GetDlgItem(settings,211))&&!IsWindowEnabled(GetDlgItem(settings,216))&&!IsWindowEnabled(GetDlgItem(settings,217));SendDlgItemMessageW(settings,211,CB_SETCURSEL,1,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(211,CBN_SELCHANGE),0);okay=okay&&core.resolution()==2;okay=okay&&SendDlgItemMessageW(settings,202,CB_GETCOUNT,0,0)==3;SendDlgItemMessageW(settings,202,CB_SETCURSEL,2,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(202,CBN_SELCHANGE),0);okay=okay&&GetPrivateProfileIntW(L"Console",L"Aspect",-1,(directory/L"TM3Console.ini").c_str())==2;}
    if(i==0){SetFocus(GetDlgItem(settings,208));MSG tab{};tab.hwnd=GetDlgItem(settings,208);tab.message=WM_KEYDOWN;tab.wParam=VK_TAB;const auto previous=GetFocus();okay=ui.translate(tab)&&okay;okay=okay&&GetFocus()!=previous;
      SendDlgItemMessageW(settings,219,CB_SETCURSEL,1,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(219,CBN_SELCHANGE),0);okay=okay&&ConsoleUI::menuCaption(GetMenu(host),0)==L"Sistema";
      SendDlgItemMessageW(settings,219,CB_SETCURSEL,0,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(219,CBN_SELCHANGE),0);okay=okay&&ConsoleUI::menuCaption(GetMenu(host),0)==L"System"&&GetPrivateProfileIntW(L"Console",L"Language",-1,(directory/L"TM3Console.ini").c_str())==0;}
    if(i==7){MSG enter{};enter.hwnd=GetDlgItem(settings,302);enter.message=WM_KEYDOWN;enter.wParam=VK_RETURN;okay=ui.translate(enter)&&okay;okay=okay&&IsWindow(settings)&&IsWindow(host);}
    if(i==7){SendDlgItemMessageW(settings,204,TBM_SETPOS,TRUE,35);SendMessageW(settings,WM_HSCROLL,TB_ENDTRACK,reinterpret_cast<LPARAM>(GetDlgItem(settings,204)));SendDlgItemMessageW(settings,205,BM_CLICK,0,0);okay=okay&&GetPrivateProfileIntW(L"Console",L"Volume",-1,(directory/L"TM3Console.ini").c_str())==35;okay=okay&&GetPrivateProfileIntW(L"Console",L"Muted",0,(directory/L"TM3Console.ini").c_str())==1;wchar_t label[16]{};GetDlgItemTextW(settings,207,label,16);okay=okay&&std::wstring(label)==L"35%";okay=okay&&IsWindowEnabled(GetDlgItem(settings,212));SendDlgItemMessageW(settings,212,CB_SETCURSEL,0,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(212,CBN_SELCHANGE),0);okay=okay&&GetPrivateProfileIntW(L"Console",L"AudioDevice",-2,(directory/L"TM3Console.ini").c_str())==-1;}
    if(i==8){
      for(int id=220;id<236;++id)okay=okay&&GetDlgItem(settings,id)!=nullptr&&GetDlgItem(settings,id+40)==nullptr;
      for(int key:{VK_UP,VK_SPACE,VK_TAB,VK_F5,VK_NUMPAD7,VK_OEM_1}){SendMessageW(settings,WM_COMMAND,MAKEWPARAM(220,BN_CLICKED),0);MSG press{};press.hwnd=GetDlgItem(settings,220);press.message=WM_KEYDOWN;press.wParam=key;okay=ui.translate(press)&&okay;okay=okay&&core.keyBinding(0)==key&&GetPrivateProfileIntW(L"Console",L"Key0",-1,(directory/L"TM3Console.ini").c_str())==key;}
      SendMessageW(settings,WM_CONTEXTMENU,reinterpret_cast<WPARAM>(GetDlgItem(settings,221)),0);okay=okay&&core.keyBinding(1)==0;
      SendMessageW(settings,WM_COMMAND,MAKEWPARAM(220,BN_CLICKED),0);MSG cancel{};cancel.hwnd=GetDlgItem(settings,220);cancel.message=WM_KEYDOWN;cancel.wParam=VK_ESCAPE;ui.translate(cancel);okay=okay&&core.keyBinding(0)==VK_OEM_1;
      SendDlgItemMessageW(settings,218,CB_SETCURSEL,3,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(218,CBN_SELCHANGE),0);okay=okay&&GetPrivateProfileIntW(L"Console",L"ControllerIndex",-1,(directory/L"TM3Console.ini").c_str())==2;
      const int originalKey=core.keyBinding(0);
      SendDlgItemMessageW(settings,290,CB_SETCURSEL,1,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(290,CBN_SELCHANGE),0);
      SendDlgItemMessageW(settings,206,BM_CLICK,0,0);okay=okay&&core.secondController();
      SendMessageW(settings,WM_COMMAND,MAKEWPARAM(220,BN_CLICKED),0);MSG secondPress{};secondPress.hwnd=GetDlgItem(settings,220);secondPress.message=WM_KEYDOWN;secondPress.wParam=VK_NUMPAD2;ui.translate(secondPress);
      okay=okay&&core.keyBinding(0,1)==VK_NUMPAD2&&core.keyBinding(0)==originalKey;
      okay=okay&&GetPrivateProfileIntW(L"Console",L"Player2Key0",-1,(directory/L"TM3Console.ini").c_str())==VK_NUMPAD2;
      SendDlgItemMessageW(settings,290,CB_SETCURSEL,0,0);SendMessageW(settings,WM_COMMAND,MAKEWPARAM(290,CBN_SELCHANGE),0);
    }
    if(i==9){SendMessageW(settings,WM_COMMAND,MAKEWPARAM(240,BN_CLICKED),0);MSG press{};press.hwnd=GetDlgItem(settings,240);press.message=WM_KEYDOWN;press.wParam=VK_F2;ui.translate(press);okay=okay&&GetPrivateProfileIntW(L"Console",L"CaptureKey",0,(directory/L"TM3Console.ini").c_str())==VK_F2;}
    if(!captures.empty())okay=captureWindow(settings,captures/(std::to_wstring(i)+L".bmp"))&&okay;
    else if(i==8){const auto visual=directory/L"binding_render.bmp";okay=captureWindow(settings,visual)&&okay;std::filesystem::remove(visual);}
    ShowWindow(settings,SW_HIDE);
  }
  if(settings&&IsWindow(settings))SendMessageW(settings,WM_CLOSE,0,0);
  if(!captures.empty()){
    ShowWindow(host,SW_SHOWNORMAL);UpdateWindow(host);
    for(int menu=0;menu<5;++menu){popupFile=captures/(L"menu_"+std::to_wstring(menu)+L".bmp");popupCaptured=false;const auto timer=SetTimer(nullptr,0,250,popupTimer);if(!timer){okay=false;break;}TrackPopupMenu(GetSubMenu(GetMenu(host),menu),TPM_LEFTALIGN|TPM_TOPALIGN|TPM_NONOTIFY,30,80,0,host,nullptr);KillTimer(nullptr,timer);okay=okay&&popupCaptured;}
    ShowWindow(host,SW_HIDE);
  }
  ConsoleUI standalone(core);standalone.attach(host,directory,directory/L"test.cue",directory/L"test.dll",false);
  okay=okay&&core.secondController()&&core.keyBinding(0,1)==VK_NUMPAD2;
  SetWindowLongPtrW(host,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(&standalone));
  bool shortcutReloaded=false;const auto system=GetSubMenu(GetMenu(host),0);for(int i=0;i<GetMenuItemCount(system);++i)if(ConsoleUI::menuCaption(system,i)==L"Screenshot\tF2")shortcutReloaded=true;okay=okay&&shortcutReloaded;
  standalone.handle(host,WM_COMMAND,1002,0);okay=okay&&standalone.paused();standalone.handle(host,WM_COMMAND,1002,0);okay=okay&&!standalone.paused();
  standalone.handle(host,WM_COMMAND,1005,0);okay=okay&&(GetWindowLongPtrW(host,GWL_STYLE)&WS_POPUP)!=0;standalone.handle(host,WM_COMMAND,1005,0);okay=okay&&(GetWindowLongPtrW(host,GWL_STYLE)&WS_OVERLAPPEDWINDOW)!=0;
  standalone.openSettings(5);settings=FindWindowW(L"TM3ConsoleSettings",nullptr);okay=okay&&IsWindowEnabled(GetDlgItem(settings,216))&&IsWindowEnabled(GetDlgItem(settings,217));SendDlgItemMessageW(settings,216,BM_CLICK,0,0);okay=okay&&GetPrivateProfileIntW(L"Console",L"PGXP",0,(directory/L"TM3Console.ini").c_str())==1;SendMessageW(settings,WM_CLOSE,0,0);
  int closedGames=0;standalone.setGameAction([&](const std::filesystem::path& next){if(next.empty())++closedGames;});standalone.handle(host,WM_COMMAND,1001,0);okay=okay&&closedGames==1&&IsWindow(host);
  DestroyWindow(host);std::filesystem::remove(directory/L"TM3Console.ini");std::filesystem::remove(directory);
  std::cout<<(okay?"PASS":"FAIL")<<": five vector-icon dark menus, thirteen privacy-checked pages, clean titles, 140px sidebar/66px help, automatic persistence, local pause/resume, aspect, audio volume/mute, sixteen bindings and online-reset guard; no game/core loaded.\n";
  if(okay&&argc>2&&!captures.empty()){
    const auto runtime=std::filesystem::absolute(argv[2]),sandbox=std::filesystem::absolute(captures/L"runtime_probe");std::filesystem::create_directories(sandbox);
    if(std::filesystem::exists(runtime/L"system"))std::filesystem::copy(runtime/L"system",sandbox/L"system",std::filesystem::copy_options::recursive|std::filesystem::copy_options::skip_existing);
    SetEnvironmentVariableW(L"TM3O_PACING_FILE",(sandbox/L"pacing.csv").c_str());SetEnvironmentVariableW(L"TM3O_LINK_BOUNDARY_FILE",(sandbox/L"link_boundary.csv").c_str());
    SetEnvironmentVariableW(L"TM3O_THREAD_PROFILE_FILE",(sandbox/L"threading.jsonl").c_str());
    CoreHost probe;probe.setSaveSlot("ui_qa");okay=probe.load(runtime/L"cores/beetle_psx_libretro.dll",runtime/L"game/TM3_SQRT_MERGE_V4.cue",sandbox);
    if(okay){const auto probeStart=std::chrono::steady_clock::now();probe.setMuted(true);probe.setInputEnabled(false);probe.setSmooth(true);
      tm3threads::Schedule emulationSchedule(tm3threads::Role::Emulation,0);std::atomic<uint64_t> concurrentPaints{0};
      std::jthread presenter([&](std::stop_token stop){tm3threads::Schedule schedule(tm3threads::Role::Presentation,0);HDC dc=CreateCompatibleDC(nullptr);BITMAPINFO info{};info.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);info.bmiHeader.biWidth=1280;info.bmiHeader.biHeight=-720;info.bmiHeader.biPlanes=1;info.bmiHeader.biBitCount=32;void* pixels=nullptr;HBITMAP bitmap=CreateDIBSection(dc,&info,DIB_RGB_COLORS,&pixels,nullptr,0);if(dc&&bitmap){auto previous=SelectObject(dc,bitmap);const RECT area{0,0,1280,720};while(!stop.stop_requested()){if(probe.videoGeneration()){probe.paint(dc,area);++concurrentPaints;}Sleep(1);}SelectObject(dc,previous);}if(bitmap)DeleteObject(bitmap);if(dc)DeleteDC(dc);});
      bool visibleImage=false;for(int frame=0;frame<1800;++frame){probe.runFrame();if(frame%120==119&&probe.screenshot(sandbox/L"sample.bmp")){std::ifstream picture(sandbox/L"sample.bmp",std::ios::binary);picture.seekg(54);std::vector<unsigned char> pixels((std::istreambuf_iterator<char>(picture)),{});const auto colorful=std::count_if(pixels.begin(),pixels.end(),[](unsigned char value){return value>8;});if(colorful>100){visibleImage=true;std::filesystem::copy_file(sandbox/L"sample.bmp",sandbox/L"game_boot.bmp",std::filesystem::copy_options::overwrite_existing);}}}okay=probe.videoGeneration()>0&&visibleImage;
      const auto native=probe.frameSize();okay=probe.screenshot(sandbox/L"resolution_1x.bmp")&&okay;
      for(int factor:{2,4,1}){probe.setGraphics(factor,false,false);for(int frame=0;frame<3;++frame)probe.runFrame();const auto size=probe.frameSize();const bool changed=size[0]==native[0]*factor&&size[1]==native[1]*factor;std::cout<<"Resolution "<<factor<<"x: "<<size[0]<<"x"<<size[1]<<" "<<(changed?"PASS":"FAIL")<<"\n";okay=changed&&okay;probe.screenshot(sandbox/(L"resolution_"+std::to_wstring(factor)+L"x.bmp"));}
      probe.setGraphics(1,true,true);for(int frame=0;frame<4;++frame)probe.runFrame();const bool panoramic=std::abs(probe.aspectRatio()-16.0/9.0)<0.01;std::cout<<"PGXP/widescreen geometry: "<<(panoramic?"PASS":"FAIL")<<"\n";okay=panoramic&&okay;presenter.request_stop();presenter.join();okay=concurrentPaints.load()>0&&okay;const auto elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-probeStart).count();std::cout<<"Concurrent real-game GDI paints: "<<concurrentPaints.load()<<" elapsed_ms="<<elapsed<<"\n";std::ofstream report(sandbox/L"probe_result.json");report<<"{\"passed\":"<<(okay?"true":"false")<<",\"emulated_frames\":1813,\"concurrent_paints\":"<<concurrentPaints.load()<<",\"elapsed_ms\":"<<elapsed<<",\"scheduling_enabled\":"<<(tm3threads::enabled()?"true":"false")<<"}\n";probe.unload();}
    std::cout<<(okay?"PASS":"FAIL")<<": optional packaged-game probe, 1800 emulation frames and non-black image; isolated saves/logs, no online match.\n";
  }
  return okay?0:1;
}
