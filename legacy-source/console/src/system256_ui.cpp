#include "console_ui.hpp"
#include <memory>
namespace {
constexpr UINT_PTR modalTimer=0x54334d;
struct Shell {CoreHost settings; ConsoleUI ui{settings}; HWND window{}; int action{}; HHOOK hook{},modalHook{}; int modalDepth{}; void (*tick)(void*){}; void* tickData{}; bool inTick{};};
thread_local Shell* current=nullptr;
LRESULT CALLBACK messages(int code,WPARAM w,LPARAM l){if(code>=0&&w==PM_REMOVE&&current){auto* msg=reinterpret_cast<MSG*>(l);if(current->ui.translate(*msg))msg->message=WM_NULL;}return CallNextHookEx(nullptr,code,w,l);}
LRESULT CALLBACK modalMessages(int code,WPARAM w,LPARAM l){
 if(code>=0&&current){auto* message=reinterpret_cast<CWPSTRUCT*>(l);auto* s=current;
  if(message->message==WM_ENTERMENULOOP||message->message==WM_ENTERSIZEMOVE){if(++s->modalDepth==1&&s->tick)SetTimer(s->window,modalTimer,16,nullptr);}
  else if(message->message==WM_EXITMENULOOP||message->message==WM_EXITSIZEMOVE){if(s->modalDepth>0&&--s->modalDepth==0)KillTimer(s->window,modalTimer);}
 }return CallNextHookEx(nullptr,code,w,l);
}
LRESULT CALLBACK windowProc(HWND h,UINT m,WPARAM w,LPARAM l,UINT_PTR,DWORD_PTR data){auto* s=reinterpret_cast<Shell*>(data);
 if(m==WM_TIMER&&w==modalTimer){if(s->tick&&!s->inTick){s->inTick=true;s->tick(s->tickData);s->inTick=false;}return 0;}
 if(m==WM_COMMAND){int id=LOWORD(w);if(id==1004){s->action=1;return 0;}if(id==1001||id==1012){PostMessageW(h,WM_CLOSE,0,0);return 0;}}
 if(m==WM_KEYDOWN||m==WM_SYSKEYDOWN)return DefSubclassProc(h,m,w,l);
 if(s->ui.handle(h,m,w,l))return m==WM_MEASUREITEM||m==WM_DRAWITEM?TRUE:0;
 return DefSubclassProc(h,m,w,l);
}
}
extern "C" __declspec(dllexport) void* tm3ui_attach(HWND window,const wchar_t* base,const wchar_t* game,int vulkan){try{auto* s=new Shell;s->window=window;SetWindowSubclass(window,windowProc,256,reinterpret_cast<DWORD_PTR>(s));s->ui.setSystem256(vulkan!=0);s->ui.attach(window,base,game,L"SYSTEM256",true);s->ui.setGameAction([s](const auto&){PostMessageW(s->window,WM_CLOSE,0,0);});SetWindowSubclass(window,windowProc,256,reinterpret_cast<DWORD_PTR>(s));current=s;s->hook=SetWindowsHookExW(WH_GETMESSAGE,messages,nullptr,GetCurrentThreadId());s->modalHook=SetWindowsHookExW(WH_CALLWNDPROC,modalMessages,nullptr,GetCurrentThreadId());return s;}catch(...){return nullptr;}}
extern "C" __declspec(dllexport) int tm3ui_poll(void* handle){auto* s=static_cast<Shell*>(handle);int action=s->action;s->action=0;return action;}
// Called through ctypes.CDLL: release Python's GIL while Windows runs modal
// menu/move/resize loops, so core/audio/transport callbacks keep executing.
extern "C" __declspec(dllexport) void tm3ui_pump(void* handle){
 auto* s=static_cast<Shell*>(handle);if(!s)return;
 MSG msg{};while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){
  if(msg.message==WM_QUIT){PostMessageW(s->window,WM_CLOSE,0,0);break;}
  TranslateMessage(&msg);DispatchMessageW(&msg);
 }
}
extern "C" __declspec(dllexport) void tm3ui_set_tick(void* handle,void (*tick)(void*),void* data){auto* s=static_cast<Shell*>(handle);if(s){s->tick=tick;s->tickData=data;}}
extern "C" __declspec(dllexport) void tm3ui_detach(void* handle){auto* s=static_cast<Shell*>(handle);if(!s)return;KillTimer(s->window,modalTimer);s->tick=nullptr;if(s->modalHook)UnhookWindowsHookEx(s->modalHook);s->ui.closeSettings();if(s->hook)UnhookWindowsHookEx(s->hook);RemoveWindowSubclass(s->window,windowProc,256);auto menu=GetMenu(s->window);SetMenu(s->window,nullptr);if(menu)DestroyMenu(menu);current=nullptr;delete s;}
