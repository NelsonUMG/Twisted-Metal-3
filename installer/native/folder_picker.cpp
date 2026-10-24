#include <windows.h>
#include <msi.h>
#include <msiquery.h>
#include <shlobj.h>
#include <filesystem>
#include <string>
#include <array>

namespace {
const std::array<const KNOWNFOLDERID*,6> folders={&FOLDERID_Desktop,&FOLDERID_Downloads,&FOLDERID_Documents,&FOLDERID_Music,&FOLDERID_Pictures,&FOLDERID_Videos};
const std::array<const wchar_t*,6> names={L"Escritorio",L"Descargas",L"Documentos",L"Música",L"Imágenes",L"Vídeos"};
std::wstring destination(int choice){
 if(choice<0||choice>=static_cast<int>(folders.size()))return {};
 PWSTR folder=nullptr;
 if(FAILED(SHGetKnownFolderPath(*folders[choice],KF_FLAG_DONT_VERIFY,nullptr,&folder)))return {};
 auto result=(std::filesystem::path(folder)/L"TM3Online").wstring();CoTaskMemFree(folder);return result;
}
struct Choice {HWND window{},combo{},hint{};HFONT font{};int selected=0;bool accepted=false;UINT dpi=96;};
void preview(Choice* state){
 state->selected=static_cast<int>(SendMessageW(state->combo,CB_GETCURSEL,0,0));
 std::wstring text=L"Se creará la carpeta TM3Online dentro de "+std::wstring(names[state->selected])+L".";
 SetWindowTextW(state->hint,text.c_str());
}
LRESULT CALLBACK procedure(HWND window,UINT message,WPARAM w,LPARAM l){
 auto* state=reinterpret_cast<Choice*>(GetWindowLongPtrW(window,GWLP_USERDATA));
 if(message==WM_NCCREATE){state=static_cast<Choice*>(reinterpret_cast<CREATESTRUCTW*>(l)->lpCreateParams);SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(state));}
 if(!state)return DefWindowProcW(window,message,w,l);
 if(message==WM_CREATE){
  const auto scale=[&](int n){return MulDiv(n,state->dpi,96);};
  const auto control=[&](const wchar_t* cls,const wchar_t* text,DWORD style,int x,int y,int width,int height,int id){
   HWND child=CreateWindowExW(0,cls,text,WS_CHILD|WS_VISIBLE|style,scale(x),scale(y),scale(width),scale(height),window,reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),GetModuleHandleW(nullptr),nullptr);
   SendMessageW(child,WM_SETFONT,reinterpret_cast<WPARAM>(state->font),TRUE);return child;
  };
  control(L"STATIC",L"¿Dónde quieres instalar TM3 Online?",0,20,18,430,24,0);
  state->combo=control(L"COMBOBOX",L"",WS_TABSTOP|CBS_DROPDOWNLIST|WS_VSCROLL,20,49,430,210,100);
  for(auto name:names)SendMessageW(state->combo,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(name));
  SendMessageW(state->combo,CB_SETCURSEL,0,0);
  state->hint=control(L"STATIC",L"",SS_LEFT,20,91,430,42,101);preview(state);
  control(L"BUTTON",L"Usar ubicación",WS_TABSTOP|BS_DEFPUSHBUTTON,224,149,116,30,IDOK);
  control(L"BUTTON",L"Cancelar",WS_TABSTOP|BS_PUSHBUTTON,350,149,100,30,IDCANCEL);
  SetFocus(state->combo);return 0;
 }
 if(message==WM_COMMAND){
  if(LOWORD(w)==100&&HIWORD(w)==CBN_SELCHANGE){preview(state);return 0;}
  if(LOWORD(w)==IDOK){state->accepted=true;DestroyWindow(window);return 0;}
  if(LOWORD(w)==IDCANCEL){DestroyWindow(window);return 0;}
 }
 if(message==WM_CLOSE){DestroyWindow(window);return 0;}
 return DefWindowProcW(window,message,w,l);
}
std::wstring choose(HWND owner){
 Choice state;state.dpi=owner?GetDpiForWindow(owner):96;
 state.font=CreateFontW(-MulDiv(10,state.dpi,72),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Segoe UI");
 WNDCLASSW cls{};cls.lpfnWndProc=procedure;cls.hInstance=GetModuleHandleW(nullptr);cls.lpszClassName=L"TM3QuickInstallLocation";cls.hCursor=LoadCursor(nullptr,IDC_ARROW);cls.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_WINDOW+1);RegisterClassW(&cls);
 RECT bounds{0,0,MulDiv(470,state.dpi,96),MulDiv(200,state.dpi,96)};AdjustWindowRectEx(&bounds,WS_CAPTION|WS_SYSMENU,FALSE,WS_EX_DLGMODALFRAME);
 RECT anchor{};if(!owner||!GetWindowRect(owner,&anchor))SystemParametersInfoW(SPI_GETWORKAREA,0,&anchor,0);
 int width=bounds.right-bounds.left,height=bounds.bottom-bounds.top;
 state.window=CreateWindowExW(WS_EX_DLGMODALFRAME,cls.lpszClassName,L"Ubicación de instalación",WS_CAPTION|WS_SYSMENU,anchor.left+(anchor.right-anchor.left-width)/2,anchor.top+(anchor.bottom-anchor.top-height)/2,width,height,owner,nullptr,cls.hInstance,&state);
 if(!state.window){DeleteObject(state.font);return {};}
 if(owner)EnableWindow(owner,FALSE);
 ShowWindow(state.window,SW_SHOWNORMAL);SetForegroundWindow(state.window);
 MSG msg{};while(IsWindow(state.window)&&GetMessageW(&msg,nullptr,0,0)>0){if(!IsDialogMessageW(state.window,&msg)){TranslateMessage(&msg);DispatchMessageW(&msg);}}
 if(owner){EnableWindow(owner,TRUE);SetForegroundWindow(owner);}
 DeleteObject(state.font);UnregisterClassW(cls.lpszClassName,cls.hInstance);
 return state.accepted?destination(state.selected):std::wstring{};
}
}
extern "C" __declspec(dllexport) UINT __stdcall PickInstallFolder(MSIHANDLE install){
 try{std::wstring result=choose(GetForegroundWindow());
  return result.empty()?ERROR_SUCCESS:MsiSetPropertyW(install,L"INSTALLFOLDER",result.c_str());
 }catch(...){return ERROR_INSTALL_FAILURE;}
}
extern "C" __declspec(dllexport) UINT __stdcall ResolveInstallLocation(int choice,wchar_t* output,UINT capacity){
 auto path=destination(choice);if(path.empty())return ERROR_INVALID_PARAMETER;
 if(!output||capacity<=path.size())return ERROR_INSUFFICIENT_BUFFER;
 wcscpy_s(output,capacity,path.c_str());return ERROR_SUCCESS;
}
