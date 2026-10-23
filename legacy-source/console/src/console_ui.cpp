#include "console_ui.hpp"
#include "keyboard_bindings.hpp"
#include "input_bindings.hpp"
#include <shellapi.h>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <dwmapi.h>
#include <uxtheme.h>
#include <commdlg.h>
#include "controller_diagram.hpp"
#include "localization.hpp"
#define SetWindowTextW tm3loc::setText
#define SetDlgItemTextW tm3loc::setDlgText
#define SendMessageW tm3loc::send
#define MessageBoxW tm3loc::message

namespace {
constexpr int closeGame=1001,pauseGame=1002,resetGame=1003,shot=1004,full=1005,stats=1006,logs=1007,about=1008,properties=1009;
constexpr const wchar_t* pages[]={L"Interfaz",L"BIOS",L"Consola",L"Emulación",L"Memory Cards",L"Gráficos",L"Mensajes en pantalla",L"Audio",L"Mandos",L"Atajos",L"Avanzado",L"Captura",L"Resumen"};
constexpr const wchar_t* helpTexts[]={L"Comportamiento y presentación de la ventana. Los cambios se guardan automáticamente.",L"El arranque del sistema se configura automáticamente.",L"Configuración de PlayStation y del lector de discos.",L"Velocidad y pausa de la emulación. En una partida en línea, usa Start dentro del juego para pausar ambos lados.",L"Las partidas se guardan automáticamente en las tarjetas de memoria.",L"Resolución interna real: 2x y 4x mejoran el detalle 3D, pero requieren más CPU. Empieza con 1x para priorizar fluidez.",L"Muestra la velocidad de emulación en el título de la ventana. No representa las actualizaciones internas del juego.",L"Ajusta el volumen local o silencia el juego.",L"Pulsa un campo y después la tecla o el botón del mando. Esc cancela y clic derecho borra. Las palancas se asignan como direcciones digitales.",L"Atajos de la interfaz. Los botones del mando se configuran en Mandos.",L"Los ajustes de compatibilidad se administran automáticamente.",L"Guarda imágenes del juego con Sistema > Captura o con el atajo asignado.",L"Información del juego actual."};
constexpr const wchar_t* buttonNames[]={L"Cruz",L"Cuadrado",L"Select",L"Start",L"Arriba",L"Abajo",L"Izquierda",L"Derecha",L"Círculo",L"Triángulo",L"L1",L"R1",L"L2",L"R2",L"L3",L"R3"};
// Small vector icons: no dependency on private-use glyphs or installed icon fonts.
void drawIcon(HDC dc,int x,int y,int id,COLORREF color){
  HPEN pen=CreatePen(PS_SOLID,1,color);auto previous=SelectObject(dc,pen);auto brush=SelectObject(dc,GetStockObject(HOLLOW_BRUSH));
  const auto line=[&](int a,int b,int c,int d){MoveToEx(dc,x+a,y+b,nullptr);LineTo(dc,x+c,y+d);};
  const auto box=[&](int a,int b,int c,int d){Rectangle(dc,x+a,y+b,x+c,y+d);};
  switch(id){
  case 1001:line(4,4,14,14);line(14,4,4,14);break;
  case 1002:box(4,3,7,16);box(11,3,14,16);break;
  case 1003:Arc(dc,x+2,y+2,x+16,y+16,x+14,y+3,x+3,y+4);line(3,0,3,5);line(3,5,8,5);break;
  case 1004:box(1,5,17,16);box(5,2,12,6);Ellipse(dc,x+6,y+7,x+13,y+14);break;
  case 1005:line(1,7,1,1);line(1,1,7,1);line(11,1,17,1);line(17,1,17,7);line(1,11,1,17);line(1,17,7,17);line(11,17,17,17);line(17,17,17,11);break;
  case 1008:Ellipse(dc,x+1,y+1,x+17,y+17);line(9,8,9,14);SetPixel(dc,x+9,y+5,color);break;
  case 1100:Ellipse(dc,x+4,y+4,x+14,y+14);Ellipse(dc,x+7,y+7,x+11,y+11);for(int a=0;a<3;++a){line(4+a*5,0,4+a*5,3);line(4+a*5,15,4+a*5,18);line(0,4+a*5,3,4+a*5);line(15,4+a*5,18,4+a*5);}break;
  case 1105:box(1,2,17,13);line(9,13,9,17);line(5,17,13,17);break;
  case 1106:box(1,10,4,17);box(7,6,10,17);box(13,1,16,17);break;
  case 1107:box(1,6,5,12);line(5,6,10,2);line(10,2,10,16);line(10,16,5,12);Arc(dc,x+8,y+3,x+17,y+16,x+14,y+4,x+14,y+15);break;
  case 1108:RoundRect(dc,x+1,y+4,x+17,y+15,5,5);line(4,9,9,9);line(6,7,6,12);Ellipse(dc,x+12,y+7,x+15,y+10);break;
  case 1109:box(1,4,17,14);for(int i=4;i<16;i+=4){line(i,6,i,8);line(i,9,i,11);}line(5,12,13,12);break;
  case 1104:box(2,1,16,17);box(5,2,13,7);box(5,11,13,16);break;
  case 1111:box(1,3,13,15);line(13,7,18,4);line(18,4,18,14);line(18,14,13,11);break;
  default:box(3,1,15,17);line(6,5,12,5);line(6,9,12,9);line(6,13,11,13);break;
  }
  SelectObject(dc,brush);SelectObject(dc,previous);DeleteObject(pen);
}
std::wstring wide(const std::string& text){if(text.empty())return {};int n=MultiByteToWideChar(CP_UTF8,0,text.data(),static_cast<int>(text.size()),nullptr,0);std::wstring value(n,L' ');MultiByteToWideChar(CP_UTF8,0,text.data(),static_cast<int>(text.size()),value.data(),n);return value;}
void append(HMENU menu,int id,const wchar_t* label,UINT flags=MF_STRING){AppendMenuW(menu,flags,id,label);}
LRESULT CALLBACK groupSkin(HWND h,UINT message,WPARAM w,LPARAM l,UINT_PTR id,DWORD_PTR font){
  if(message==WM_ERASEBKGND)return 1;
  if(message==WM_PAINT||message==WM_PRINTCLIENT){PAINTSTRUCT paint{};HDC dc=message==WM_PAINT?BeginPaint(h,&paint):reinterpret_cast<HDC>(w);RECT rect{};GetClientRect(h,&rect);HBRUSH fill=CreateSolidBrush(RGB(22,29,41));FillRect(dc,&rect,fill);auto oldFont=SelectObject(dc,reinterpret_cast<HFONT>(font));wchar_t title[180]{};GetWindowTextW(h,title,180);SIZE extent{};GetTextExtentPoint32W(dc,title,lstrlenW(title),&extent);HPEN pen=CreatePen(PS_SOLID,1,RGB(78,78,78));auto oldPen=SelectObject(dc,pen);auto oldBrush=SelectObject(dc,GetStockObject(HOLLOW_BRUSH));Rectangle(dc,0,extent.cy/2,rect.right,rect.bottom);RECT caption{10,0,extent.cx+20,extent.cy};FillRect(dc,&caption,fill);caption.left+=4;SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(230,230,230));DrawTextW(dc,title,-1,&caption,DT_SINGLELINE);SelectObject(dc,oldBrush);SelectObject(dc,oldPen);SelectObject(dc,oldFont);DeleteObject(pen);DeleteObject(fill);if(message==WM_PAINT)EndPaint(h,&paint);return 0;}
  if(message==WM_NCDESTROY)RemoveWindowSubclass(h,groupSkin,id);
  return DefSubclassProc(h,message,w,l);
}
LRESULT CALLBACK comboSkin(HWND h,UINT message,WPARAM w,LPARAM l,UINT_PTR id,DWORD_PTR){
  const auto result=DefSubclassProc(h,message,w,l);
  if(message==WM_PAINT||message==WM_PRINTCLIENT){HDC dc=message==WM_PAINT?GetDC(h):reinterpret_cast<HDC>(w);RECT rect{};GetClientRect(h,&rect);RECT arrow=rect;arrow.left=std::max(0L,rect.right-24);HBRUSH fill=CreateSolidBrush(RGB(45,45,45));FillRect(dc,&arrow,fill);DeleteObject(fill);SetBkMode(dc,TRANSPARENT);SetTextColor(dc,IsWindowEnabled(h)?RGB(235,235,235):RGB(115,115,115));DrawTextW(dc,L"▾",-1,&arrow,DT_CENTER|DT_VCENTER|DT_SINGLELINE);HPEN pen=CreatePen(PS_SOLID,1,RGB(65,82,108));auto previous=SelectObject(dc,pen);auto brush=SelectObject(dc,GetStockObject(HOLLOW_BRUSH));Rectangle(dc,rect.left,rect.top,rect.right,rect.bottom);SelectObject(dc,brush);SelectObject(dc,previous);DeleteObject(pen);if(message==WM_PAINT)ReleaseDC(h,dc);}
  if(message==WM_NCDESTROY)RemoveWindowSubclass(h,comboSkin,id);
  return result;
}
}

namespace {
LRESULT CALLBACK checkboxSkin(HWND h,UINT message,WPARAM w,LPARAM l,UINT_PTR id,DWORD_PTR font){
  if(message==WM_PAINT||message==WM_PRINTCLIENT){
    PAINTSTRUCT paint{};HDC dc=message==WM_PAINT?BeginPaint(h,&paint):reinterpret_cast<HDC>(w);RECT rect{};GetClientRect(h,&rect);
    HBRUSH background=CreateSolidBrush(RGB(22,29,41));FillRect(dc,&rect,background);DeleteObject(background);
    const bool checked=SendMessageW(h,BM_GETCHECK,0,0)==BST_CHECKED,enabled=IsWindowEnabled(h)!=FALSE;
    RECT box{2,(rect.bottom-14)/2,16,(rect.bottom+14)/2};HBRUSH fill=CreateSolidBrush(checked?RGB(56,113,171):RGB(40,40,40));FillRect(dc,&box,fill);DeleteObject(fill);
    HPEN pen=CreatePen(PS_SOLID,1,enabled?RGB(165,165,165):RGB(90,90,90));auto previous=SelectObject(dc,pen);auto brush=SelectObject(dc,GetStockObject(HOLLOW_BRUSH));Rectangle(dc,box.left,box.top,box.right,box.bottom);SelectObject(dc,brush);SelectObject(dc,previous);DeleteObject(pen);
    if(checked){pen=CreatePen(PS_SOLID,2,RGB(245,245,245));previous=SelectObject(dc,pen);MoveToEx(dc,box.left+3,box.top+7,nullptr);LineTo(dc,box.left+6,box.top+10);LineTo(dc,box.left+11,box.top+4);SelectObject(dc,previous);DeleteObject(pen);}
    auto previousFont=SelectObject(dc,reinterpret_cast<HFONT>(font));SetBkMode(dc,TRANSPARENT);SetTextColor(dc,enabled?RGB(235,235,235):RGB(120,120,120));wchar_t text[240]{};GetWindowTextW(h,text,240);rect.left=24;DrawTextW(dc,text,-1,&rect,DT_SINGLELINE|DT_VCENTER);if(GetFocus()==h)DrawFocusRect(dc,&rect);SelectObject(dc,previousFont);
    if(message==WM_PAINT)EndPaint(h,&paint);return 0;
  }
  const auto result=DefSubclassProc(h,message,w,l);if(message==BM_SETCHECK||message==WM_SETFOCUS||message==WM_KILLFOCUS||message==WM_KEYUP||message==WM_LBUTTONUP)InvalidateRect(h,nullptr,FALSE);if(message==WM_NCDESTROY)RemoveWindowSubclass(h,checkboxSkin,id);return result;
}
LRESULT CALLBACK helpSkin(HWND h,UINT message,WPARAM w,LPARAM l,UINT_PTR id,DWORD_PTR font){
  if(message==WM_PAINT||message==WM_PRINTCLIENT){PAINTSTRUCT paint{};HDC dc=message==WM_PAINT?BeginPaint(h,&paint):reinterpret_cast<HDC>(w);RECT rect{};GetClientRect(h,&rect);HBRUSH fill=CreateSolidBrush(RGB(26,36,51));FillRect(dc,&rect,fill);DeleteObject(fill);auto previous=SelectObject(dc,reinterpret_cast<HFONT>(font));SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(205,205,205));InflateRect(&rect,-12,-12);wchar_t text[1024]{};GetWindowTextW(h,text,1024);DrawTextW(dc,text,-1,&rect,DT_WORDBREAK);SelectObject(dc,previous);if(message==WM_PAINT)EndPaint(h,&paint);return 0;}if(message==WM_NCDESTROY)RemoveWindowSubclass(h,helpSkin,id);return DefSubclassProc(h,message,w,l);
}
}

void ConsoleUI::item(HMENU menu,int id,const wchar_t* label,UINT flags,bool bar){
  auto record=std::make_unique<MenuLabel>();record->text=tm3loc::translate(label);record->bar=bar;record->id=id;
  AppendMenuW(menu,flags|MF_OWNERDRAW,static_cast<UINT_PTR>(id),reinterpret_cast<LPCWSTR>(record.get()));menuLabels_.push_back(std::move(record));
}
void ConsoleUI::separator(HMENU menu){auto record=std::make_unique<MenuLabel>();record->separator=true;AppendMenuW(menu,MF_OWNERDRAW|MF_DISABLED,0,reinterpret_cast<LPCWSTR>(record.get()));menuLabels_.push_back(std::move(record));}
std::wstring ConsoleUI::windowCaption(bool linked,bool statistics,double fps){std::wostringstream text;text<<L"Twisted Metal III Online";if(linked)text<<L" — En línea";if(statistics)text<<L" | "<<std::fixed<<std::setprecision(1)<<fps<<L" FPS";return text.str();}
bool ConsoleUI::translate(MSG& message){
  if(settings_&&captureId_&&(message.hwnd==settings_||IsChild(settings_,message.hwnd))&&(message.message==WM_KEYDOWN||message.message==WM_SYSKEYDOWN)){
    int key=static_cast<int>(message.wParam);if(key==VK_ESCAPE)finishBinding(0,true);
    else if(captureId_<260){finishBinding(tm3input::virtualKey(message.wParam,message.lParam));}return true;
  }
  return settings_&&IsDialogMessageW(settings_,&message);
}
std::wstring ConsoleUI::menuCaption(HMENU menu,int index){MENUITEMINFOW info{sizeof(info)};info.fMask=MIIM_DATA;if(!GetMenuItemInfoW(menu,index,TRUE,&info)||!info.dwItemData)return {};return reinterpret_cast<MenuLabel*>(info.dwItemData)->text;}
bool ConsoleUI::draw(UINT message,LPARAM l){
  if(message==WM_MEASUREITEM){auto* measure=reinterpret_cast<MEASUREITEMSTRUCT*>(l);if(measure->CtlType==ODT_MENU){auto* value=reinterpret_cast<MenuLabel*>(measure->itemData);HDC dc=GetDC(window_);auto old=SelectObject(dc,font_);SIZE extent{};GetTextExtentPoint32W(dc,value->text.c_str(),static_cast<int>(value->text.size()),&extent);SelectObject(dc,old);ReleaseDC(window_,dc);measure->itemWidth=value->separator?0:extent.cx+(value->bar?22:65);measure->itemHeight=value->separator?9:value->bar?25:29;return true;}if(measure->CtlType==ODT_LISTBOX){measure->itemHeight=38;return true;}if(measure->CtlType==ODT_COMBOBOX){measure->itemHeight=24;return true;}}
  if(message!=WM_DRAWITEM)return false;
  auto* draw=reinterpret_cast<DRAWITEMSTRUCT*>(l);
  if(draw->CtlType==ODT_BUTTON){const bool checkbox=GetWindowLongPtrW(draw->hwndItem,GWLP_USERDATA)==1;const bool disabled=!IsWindowEnabled(draw->hwndItem);RECT rect=draw->rcItem;HBRUSH fill=CreateSolidBrush(checkbox?RGB(22,29,41):(draw->itemState&ODS_SELECTED)?RGB(70,70,70):RGB(35,49,69));FillRect(draw->hDC,&rect,fill);DeleteObject(fill);HPEN pen=CreatePen(PS_SOLID,1,RGB(65,82,108));auto oldPen=SelectObject(draw->hDC,pen);auto oldBrush=SelectObject(draw->hDC,GetStockObject(HOLLOW_BRUSH));if(checkbox)Rectangle(draw->hDC,rect.left+2,rect.top+7,rect.left+14,rect.top+19);else Rectangle(draw->hDC,rect.left,rect.top,rect.right,rect.bottom);SelectObject(draw->hDC,oldPen);SelectObject(draw->hDC,oldBrush);DeleteObject(pen);wchar_t text[240]{};GetWindowTextW(draw->hwndItem,text,240);SetBkMode(draw->hDC,TRANSPARENT);SetTextColor(draw->hDC,disabled?RGB(120,120,120):RGB(235,235,235));auto oldFont=SelectObject(draw->hDC,font_);if(checkbox)rect.left+=23;DrawTextW(draw->hDC,text,-1,&rect,DT_SINGLELINE|DT_VCENTER|DT_END_ELLIPSIS|(checkbox?DT_LEFT:DT_CENTER));SelectObject(draw->hDC,oldFont);return true;}
  if(draw->CtlType==ODT_COMBOBOX){RECT rect=draw->rcItem;HBRUSH fill=CreateSolidBrush(draw->itemState&ODS_SELECTED?RGB(40,68,105):RGB(40,40,40));FillRect(draw->hDC,&rect,fill);DeleteObject(fill);wchar_t text[400]{};if(draw->itemID!=static_cast<UINT>(-1))SendMessageW(draw->hwndItem,CB_GETLBTEXT,draw->itemID,reinterpret_cast<LPARAM>(text));SetBkMode(draw->hDC,TRANSPARENT);SetTextColor(draw->hDC,IsWindowEnabled(draw->hwndItem)?RGB(235,235,235):RGB(120,120,120));auto oldFont=SelectObject(draw->hDC,font_);rect.left+=8;DrawTextW(draw->hDC,text,-1,&rect,DT_SINGLELINE|DT_VCENTER|DT_END_ELLIPSIS);SelectObject(draw->hDC,oldFont);return true;}
  if(draw->CtlType==ODT_MENU){auto* value=reinterpret_cast<MenuLabel*>(draw->itemData);if(!value)return false;HBRUSH fill=CreateSolidBrush((draw->itemState&ODS_SELECTED)?RGB(40,68,105):RGB(22,29,41));FillRect(draw->hDC,&draw->rcItem,fill);DeleteObject(fill);if(value->separator){HPEN line=CreatePen(PS_SOLID,1,RGB(70,70,70));auto previous=SelectObject(draw->hDC,line);const int y=(draw->rcItem.top+draw->rcItem.bottom)/2;MoveToEx(draw->hDC,draw->rcItem.left+9,y,nullptr);LineTo(draw->hDC,draw->rcItem.right-9,y);SelectObject(draw->hDC,previous);DeleteObject(line);return true;}SetBkMode(draw->hDC,TRANSPARENT);SetTextColor(draw->hDC,(draw->itemState&ODS_DISABLED)?RGB(122,122,122):RGB(235,235,235));auto old=SelectObject(draw->hDC,font_);RECT text=draw->rcItem;text.left+=value->bar?8:32;text.right-=12;const auto split=value->text.find(L'\t');const auto label=value->text.substr(0,split);DrawTextW(draw->hDC,label.c_str(),-1,&text,DT_SINGLELINE|DT_VCENTER);if(split!=std::wstring::npos)DrawTextW(draw->hDC,value->text.substr(split+1).c_str(),-1,&text,DT_SINGLELINE|DT_VCENTER|DT_RIGHT);if(draw->itemState&ODS_CHECKED){RECT tick=draw->rcItem;tick.left+=8;DrawTextW(draw->hDC,L"✓",-1,&tick,DT_SINGLELINE|DT_VCENTER);}if(!value->bar&&!(draw->itemState&ODS_CHECKED)){drawIcon(draw->hDC,draw->rcItem.left+7,draw->rcItem.top+(draw->rcItem.bottom-draw->rcItem.top-18)/2,value->id,(draw->itemState&ODS_DISABLED)?RGB(122,122,122):RGB(220,220,220));}SelectObject(draw->hDC,old);return true;}
  if(draw->CtlType==ODT_LISTBOX&&draw->itemID!=static_cast<UINT>(-1)){wchar_t text[160]{};SendMessageW(draw->hwndItem,LB_GETTEXT,draw->itemID,reinterpret_cast<LPARAM>(text));const bool disabled=draw->itemID<navigation_.size()&&navigation_[draw->itemID]<0;HBRUSH fill=CreateSolidBrush((draw->itemState&ODS_SELECTED)?RGB(40,68,105):RGB(22,29,41));FillRect(draw->hDC,&draw->rcItem,fill);DeleteObject(fill);SetBkMode(draw->hDC,TRANSPARENT);SetTextColor(draw->hDC,disabled?RGB(115,115,115):RGB(235,235,235));auto old=SelectObject(draw->hDC,font_);RECT rect=draw->rcItem;rect.left+=40;rect.right-=6;RECT measure=rect;DrawTextW(draw->hDC,text,-1,&measure,DT_LEFT|DT_WORDBREAK|DT_CALCRECT);rect.top+=(rect.bottom-rect.top-(measure.bottom-measure.top))/2;DrawTextW(draw->hDC,text,-1,&rect,DT_LEFT|DT_WORDBREAK);const int pageId=draw->itemID<navigation_.size()?navigation_[draw->itemID]:-1;drawIcon(draw->hDC,draw->rcItem.left+10,draw->rcItem.top+10,1100+pageId,disabled?RGB(115,115,115):RGB(220,220,220));SelectObject(draw->hDC,old);return true;}
  return false;
}

void ConsoleUI::attach(HWND window,const std::filesystem::path& base,const std::filesystem::path& game,const std::filesystem::path& engine,bool linked){
  window_=window;base_=base;game_=game;engine_=engine;linked_=linked;ini_=base/L"TM3Console.ini";
  language_=GetPrivateProfileIntW(L"Console",L"Language",0,ini_.c_str())==1?1:0;tm3loc::spanish=language_==1;
  wchar_t bios[32768]{};GetPrivateProfileStringW(L"Console",L"BIOS",L"",bios,32768,ini_.c_str());bios_=bios;
  latency_=GetPrivateProfileIntW(L"Console",L"AudioLatency",80,ini_.c_str());
  deinterlace_=std::clamp(static_cast<int>(GetPrivateProfileIntW(L"Console",L"Deinterlace",0,ini_.c_str())),0,4);
  overscan_=std::clamp(static_cast<int>(GetPrivateProfileIntW(L"Console",L"Overscan",0,ini_.c_str())),0,2);
  const auto value=[&](const wchar_t* key,int fallback){return static_cast<int>(GetPrivateProfileIntW(L"Console",key,fallback,ini_.c_str()));};
  aspect_=std::clamp(value(L"Aspect",0),0,2);volume_=std::clamp(value(L"Volume",100),0,200);
  resolution_=value(L"Resolution",1);if(resolution_!=1&&resolution_!=2&&resolution_!=4)resolution_=1;
  pgxp_=value(L"PGXP",0)!=0;widescreen_=value(L"Widescreen",0)!=0;controllerIndex_=std::clamp(value(L"ControllerIndex",-1),-1,3);audioDevice_=value(L"AudioDevice",-1);if(audioDevice_<-1||audioDevice_>=static_cast<int>(waveOutGetNumDevs()))audioDevice_=-1;
  wchar_t audioName[256]{};GetPrivateProfileStringW(L"Console",L"AudioDeviceName",L"",audioName,256,ini_.c_str());if(audioName[0]){audioDevice_=-1;for(UINT id=0;id<waveOutGetNumDevs();++id){WAVEOUTCAPSW caps{};if(waveOutGetDevCapsW(id,&caps,sizeof(caps))==MMSYSERR_NOERROR&&std::wstring(audioName)==caps.szPname){audioDevice_=static_cast<int>(id);break;}}}
  smooth_=value(L"Smooth",0)!=0;muted_=value(L"Muted",0)!=0;stats_=value(L"Statistics",0)!=0;controller_=value(L"Controller",1)!=0;
  confirmClose_=value(L"ConfirmClose",0)!=0;doubleClick_=value(L"DoubleClickFullscreen",1)!=0;
  startFullscreen_=value(L"StartFullscreen",0)!=0;captureKey_=value(L"CaptureKey",VK_F10);fullscreenKey_=value(L"FullscreenKey",VK_F11);exitKey_=value(L"ExitKey",VK_ESCAPE);
  for(unsigned i=0;i<16;++i){const auto key=L"Key"+std::to_wstring(i);keys_[i]=std::clamp(value(key.c_str(),tm3keyboard::keys[i]),0,255);const auto pad=L"Pad"+std::to_wstring(i);pads_[i]=std::clamp(value(pad.c_str(),tm3input::pads[i]),0,24);}
  secondController_=value(L"Player2Enabled",0)!=0;controllerIndex2_=std::clamp(value(L"Player2ControllerIndex",-1),-1,3);
  for(unsigned i=0;i<16;++i){const auto key=L"Player2Key"+std::to_wstring(i);keys2_[i]=std::clamp(value(key.c_str(),tm3keyboard::keys2[i]),0,255);const auto pad=L"Player2Pad"+std::to_wstring(i);pads2_[i]=std::clamp(value(pad.c_str(),tm3input::pads[i]),0,24);}
  updateCore();
  font_=CreateFontW(-16,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,DEFAULT_QUALITY,DEFAULT_PITCH,L"Segoe UI");
  iconFont_=CreateFontW(-18,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,DEFAULT_QUALITY,DEFAULT_PITCH,L"Segoe MDL2 Assets");
  buildMenu();
  fullscreen_=(GetWindowLongPtrW(window_,GWL_STYLE)&WS_POPUP)!=0;
  if(fullscreen_)restored_={20,40,920,740};
  if(startFullscreen_&&!fullscreen_)fullscreen();
}
void ConsoleUI::buildMenu(){
  HMENU previous=GetMenu(window_);SetMenu(window_,nullptr);if(previous)DestroyMenu(previous);menuLabels_.clear();
  HMENU bar=CreateMenu(),system=CreatePopupMenu(),settings=CreatePopupMenu(),view=CreatePopupMenu(),tools=CreatePopupMenu(),help=CreatePopupMenu();
  const auto disabled=[&](HMENU menu,const wchar_t* text){item(menu,1900+static_cast<int>(GetMenuItemCount(menu)),text,MF_GRAYED);};
  item(system,1010,tr(L"Open game...\tCtrl+O",L"Abrir juego...\tCtrl+O"),linked_?MF_GRAYED:0);
  separator(system);if(linked_)item(system,1012,tr(L"Cancel online game / Return to main menu",L"Cancelar partida online / Volver al menú principal"));item(system,closeGame,L"Cerrar juego",game_.empty()?MF_GRAYED:0);item(system,resetGame,L"Reiniciar juego",linked_||game_.empty()?MF_GRAYED:0);item(system,pauseGame,L"Pausar",linked_||game_.empty()?MF_GRAYED:0);
  separator(system);item(system,shot,L"Captura\tF10");separator(system);item(system,1011,L"Salir");
  item(settings,properties,L"Propiedades del juego");separator(settings);
  item(settings,1100,L"Interfaz");for(int i=1;i<=7;++i)item(settings,1100+i,pages[i]);item(settings,1111,L"Capturas de pantalla");item(settings,1110,L"Avanzado");
  separator(settings);item(settings,1108,L"Mandos");item(settings,1109,L"Atajos");
  item(view,stats,L"Estadísticas de rendimiento",stats_?MF_CHECKED:0);separator(view);item(view,full,L"Pantalla completa\tF11");
  item(tools,1108,L"Probar y configurar mandos");item(tools,1104,L"Memory Cards");separator(tools);item(tools,shot,L"Captura de pantalla");
  item(help,about,L"Acerca de TM3 Online");
  const auto top=[&](HMENU sub,const wchar_t* name){auto record=std::make_unique<MenuLabel>();record->text=tm3loc::translate(name);record->bar=true;AppendMenuW(bar,MF_POPUP|MF_OWNERDRAW,reinterpret_cast<UINT_PTR>(sub),reinterpret_cast<LPCWSTR>(record.get()));menuLabels_.push_back(std::move(record));};
  top(system,L"Sistema");top(settings,L"Ajustes");top(view,L"Vista");top(tools,L"Herramientas");top(help,L"Ayuda");
  MENUINFO info{sizeof(info)};info.fMask=MIM_BACKGROUND|MIM_APPLYTOSUBMENUS;info.hbrBack=background_;SetMenuInfo(bar,&info);
  BOOL dark=TRUE;DwmSetWindowAttribute(window_,20,&dark,sizeof(dark));
  SetMenu(window_,bar);DrawMenuBar(window_);
  syncMenu();
}

void ConsoleUI::updateCore(){core_.setAspect(aspect_);core_.setSmooth(smooth_);core_.setGraphics(resolution_,pgxp_&&!linked_,widescreen_&&!linked_);core_.setVolume(volume_);core_.setMuted(muted_);core_.setAudioDevice(audioDevice_);core_.setAudioLatency(latency_);const char* methods[]={"weave","bob","bob_offset","fastmad","off"};core_.setOption("deinterlacer",methods[deinterlace_]);core_.setController(controller_);core_.setControllerIndex(controllerIndex_);core_.setSecondController(secondController_,controllerIndex2_);for(unsigned i=0;i<16;++i){core_.setKey(i,keys_[i]);core_.setPad(i,pads_[i]);core_.setKey(i,keys2_[i],1);core_.setPad(i,pads2_[i],1);}}
void ConsoleUI::save(){
  const auto put=[&](const wchar_t* key,int value){const auto text=std::to_wstring(value);WritePrivateProfileStringW(L"Console",key,text.c_str(),ini_.c_str());};
  put(L"Aspect",aspect_);put(L"Volume",volume_);put(L"Smooth",smooth_);put(L"Muted",muted_);put(L"Statistics",stats_);put(L"Controller",controller_);
  put(L"Language",language_);put(L"AudioLatency",latency_);put(L"Deinterlace",deinterlace_);put(L"Overscan",overscan_);
  WritePrivateProfileStringW(L"Console",L"BIOS",bios_.c_str(),ini_.c_str());
  put(L"Resolution",resolution_);put(L"PGXP",pgxp_);put(L"Widescreen",widescreen_);put(L"ControllerIndex",controllerIndex_);put(L"AudioDevice",audioDevice_);
  WAVEOUTCAPSW audioCaps{};if(audioDevice_>=0)waveOutGetDevCapsW(audioDevice_,&audioCaps,sizeof(audioCaps));WritePrivateProfileStringW(L"Console",L"AudioDeviceName",audioCaps.szPname,ini_.c_str());
  put(L"ConfirmClose",confirmClose_);put(L"DoubleClickFullscreen",doubleClick_);put(L"StartFullscreen",startFullscreen_);
  put(L"CaptureKey",captureKey_);put(L"FullscreenKey",fullscreenKey_);put(L"ExitKey",exitKey_);
  for(unsigned i=0;i<16;++i){const auto key=L"Key"+std::to_wstring(i);put(key.c_str(),keys_[i]);const auto pad=L"Pad"+std::to_wstring(i);put(pad.c_str(),pads_[i]);}
  put(L"Player2Enabled",secondController_);put(L"Player2ControllerIndex",controllerIndex2_);
  for(unsigned i=0;i<16;++i){const auto key=L"Player2Key"+std::to_wstring(i);put(key.c_str(),keys2_[i]);const auto pad=L"Player2Pad"+std::to_wstring(i);put(pad.c_str(),pads2_[i]);}
  syncMenu();
}
void ConsoleUI::syncMenu(){
  const auto hotkey=[](int code){return code?tm3input::keyName(code):std::wstring();};
  for(auto& label:menuLabels_)if(!label->bar&&(label->id==shot||label->id==full)){const auto index=label->text.find(L'\t');label->text=label->text.substr(0,index);const auto key=hotkey(label->id==shot?captureKey_:fullscreenKey_);if(!key.empty())label->text+=L"\t"+key;}
  CheckMenuItem(GetMenu(window_),stats,MF_BYCOMMAND|(stats_?MF_CHECKED:MF_UNCHECKED));DrawMenuBar(window_);
}
void ConsoleUI::folder(const std::filesystem::path& path){std::error_code error;std::filesystem::create_directories(path,error);ShellExecuteW(window_,L"open",path.c_str(),nullptr,nullptr,SW_SHOWNORMAL);}
void ConsoleUI::refreshLanguage(){
  tm3loc::spanish=!english();buildMenu();
  if(settings_){SetDlgItemTextW(settings_,302,tr(L"Close",L"Cerrar"));SetDlgItemTextW(settings_,306,tr(L"Restore defaults",L"Restablecer valores"));navigation();page();}
  SetWindowTextW(window_,caption(0).c_str());InvalidateRect(window_,nullptr,TRUE);
}
void ConsoleUI::contentChanged(const std::filesystem::path& game,bool linked){
  game_=game;linked_=linked;paused_.store(false);updateCore();buildMenu();
  if(settings_)page();InvalidateRect(window_,nullptr,TRUE);
}
std::wstring ConsoleUI::caption(double fps) const{
  std::wstring title=L"TM3 Online";
  if(!game_.empty())title+=L" — "+(game_.filename()==L"TM3_SQRT_MERGE_V4.cue"?std::wstring(L"Twisted Metal III"):game_.stem().wstring());
  if(linked_)title+=tr(L" · Linked",L" · En línea");
  if(stats_&&core_.loaded()){std::wostringstream rate;rate<<L" | "<<std::fixed<<std::setprecision(1)<<fps<<L" FPS";title+=rate.str();}return title;
}
void ConsoleUI::openGame(){
  if(linked_)return;
  wchar_t path[32768]{};OPENFILENAMEW picker{sizeof(picker)};picker.hwndOwner=window_;picker.lpstrFile=path;picker.nMaxFile=32768;
  picker.lpstrFilter=L"PlayStation images (*.cue;*.chd;*.pbp;*.ccd;*.iso;*.m3u)\0*.cue;*.chd;*.pbp;*.ccd;*.iso;*.m3u\0All files\0*.*\0";
  picker.lpstrTitle=tr(L"Open a PlayStation game",L"Abrir un juego de PlayStation");picker.Flags=OFN_FILEMUSTEXIST|OFN_PATHMUSTEXIST|OFN_NOCHANGEDIR;
  if(GetOpenFileNameW(&picker)&&gameAction_)gameAction_(path);
}
void ConsoleUI::selectBios(){
  wchar_t path[32768]{};OPENFILENAMEW picker{sizeof(picker)};picker.hwndOwner=settings_;picker.lpstrFile=path;picker.nMaxFile=32768;
  picker.lpstrFilter=L"PS1 BIOS (*.bin;*.rom)\0*.bin;*.rom\0All files\0*.*\0";picker.Flags=OFN_FILEMUSTEXIST|OFN_PATHMUSTEXIST|OFN_NOCHANGEDIR;
  picker.lpstrTitle=tr(L"Choose a PS1 BIOS image",L"Elegir una imagen BIOS de PS1");
  if(GetOpenFileNameW(&picker)){std::error_code error;const auto bytes=std::filesystem::file_size(path,error);if(error||bytes!=524288){MessageBoxW(settings_,tr(L"Select a 512 KiB PlayStation BIOS image.",L"Selecciona una imagen BIOS de PlayStation de 512 KiB."),L"BIOS",MB_ICONERROR);return;}bios_=path;save();page();}
}
void ConsoleUI::paintHome(HDC dc,const RECT& bounds){
  HBRUSH fill=CreateSolidBrush(RGB(17,22,31));FillRect(dc,&bounds,fill);DeleteObject(fill);SetBkMode(dc,TRANSPARENT);
  HFONT title=CreateFontW(-38,0,0,0,FW_SEMIBOLD,0,0,0,DEFAULT_CHARSET,0,0,ANTIALIASED_QUALITY,0,L"Segoe UI");auto old=SelectObject(dc,title);
  RECT area=bounds;area.top=bounds.bottom/2-90;SetTextColor(dc,RGB(225,232,244));DrawTextW(dc,tr(L"Ready to play",L"Todo listo para jugar"),-1,&area,DT_CENTER|DT_SINGLELINE);
  SelectObject(dc,font_);area.top+=65;SetTextColor(dc,RGB(150,169,196));DrawTextW(dc,tr(L"Open a PlayStation game to begin",L"Abre un juego de PlayStation para comenzar"),-1,&area,DT_CENTER|DT_SINGLELINE);
  area.top+=50;SetTextColor(dc,RGB(126,174,255));DrawTextW(dc,tr(L"Click here or press Ctrl+O",L"Haz clic aquí o pulsa Ctrl+O"),-1,&area,DT_CENTER|DT_SINGLELINE);
  SelectObject(dc,old);DeleteObject(title);
}
void ConsoleUI::capture(){auto path=base_/L"captures";std::filesystem::create_directories(path);path/=L"TM3_"+std::to_wstring(GetTickCount64())+L".bmp";if(core_.screenshot(path))MessageBoxW(window_,L"La imagen se guardó en tus capturas.",L"Captura guardada",MB_OK);else MessageBoxW(window_,L"Todavía no hay una imagen del juego para capturar.",L"Captura",MB_OK);}
void ConsoleUI::fullscreen(){if(!fullscreen_){GetWindowRect(window_,&restored_);SetWindowLongPtrW(window_,GWL_STYLE,WS_POPUP|WS_VISIBLE);MONITORINFO monitor{sizeof(monitor)};GetMonitorInfoW(MonitorFromWindow(window_,MONITOR_DEFAULTTONEAREST),&monitor);SetWindowPos(window_,HWND_TOP,monitor.rcMonitor.left,monitor.rcMonitor.top,monitor.rcMonitor.right-monitor.rcMonitor.left,monitor.rcMonitor.bottom-monitor.rcMonitor.top,SWP_FRAMECHANGED);}else{SetWindowLongPtrW(window_,GWL_STYLE,WS_OVERLAPPEDWINDOW|WS_VISIBLE);SetWindowPos(window_,nullptr,restored_.left,restored_.top,restored_.right-restored_.left,restored_.bottom-restored_.top,SWP_FRAMECHANGED|SWP_NOZORDER);}fullscreen_=!fullscreen_;}

bool ConsoleUI::handle(HWND,UINT message,WPARAM w,LPARAM l){
  if(message==WM_KEYDOWN&&w=='O'&&(GetKeyState(VK_CONTROL)&0x8000)){openGame();return true;}
  if(message==WM_LBUTTONUP&&game_.empty()){openGame();return true;}
  if(draw(message,l))return true;
  if(message==WM_CLOSE&&confirmClose_){if(MessageBoxW(window_,L"¿Quieres cerrar el juego?",L"Cerrar juego",MB_YESNO|MB_ICONQUESTION)!=IDYES)return true;}
  if(message==WM_LBUTTONDBLCLK&&doubleClick_){fullscreen();return true;}
  int id=0;if(message==WM_COMMAND)id=LOWORD(w);else if(message==WM_KEYDOWN||message==WM_SYSKEYDOWN){if(l&(1u<<30))return false;const int key=tm3input::virtualKey(w,l);if(fullscreenKey_&&key==fullscreenKey_)id=full;else if(captureKey_&&key==captureKey_)id=shot;else if(exitKey_&&key==exitKey_)id=closeGame;}
  if(id>=1100&&id<1112){openSettings(id-1100);return true;}
  switch(id){
  case 1012:if(linked_)core_.net().requestReturnToMenu();return true;
  case 1010:openGame();return true;
  case 1011:PostMessageW(window_,WM_CLOSE,0,0);return true;
  case closeGame:if(message==WM_KEYDOWN&&linked_){core_.net().requestReturnToMenu();return true;}if(gameAction_&&!game_.empty()){if(!confirmClose_||MessageBoxW(window_,L"¿Quieres cerrar el juego?",L"Cerrar juego",MB_YESNO|MB_ICONQUESTION)==IDYES)gameAction_({});}return true;
  case pauseGame:if(!linked_){const bool value=!paused_.load();paused_.store(value);CheckMenuItem(GetMenu(window_),pauseGame,MF_BYCOMMAND|(value?MF_CHECKED:MF_UNCHECKED));}return true;
  case resetGame:if(!linked_)core_.requestReset();return true;
  case shot:capture();return true;
  case full:fullscreen();return true;
  case stats:stats_=!stats_;save();return true;
  case logs:{wchar_t target[32768]{};const auto n=GetEnvironmentVariableW(L"TM3O_LINK_BOUNDARY_FILE",target,32768);folder(n&&n<32768?std::filesystem::path(target).parent_path():base_);return true;}
  case properties:openSettings(12);return true;
  case about:MessageBoxW(window_,L"TM3 Online\nTwisted Metal III\nJuego local y partidas en línea para dos jugadores.",L"Acerca de",MB_OK);return true;
  default:return false;}
}

HWND ConsoleUI::make(const wchar_t* cls,const wchar_t* text,DWORD style,int x,int y,int width,int height,int id){
  const bool group=std::wstring(cls)==L"BUTTON"&&(style&BS_TYPEMASK)==BS_GROUPBOX;
  if(std::wstring(cls)==L"BUTTON"&&(style&BS_TYPEMASK)==BS_PUSHBUTTON)style=(style&~BS_TYPEMASK)|BS_OWNERDRAW;
  if(std::wstring(cls)==L"COMBOBOX")style|=CBS_OWNERDRAWFIXED|CBS_HASSTRINGS;
  const auto localized=tm3loc::translate(text);auto h=CreateWindowW(cls,localized.c_str(),WS_CHILD|WS_VISIBLE|style,x+200,y+12,width,height,settings_,reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),GetModuleHandleW(nullptr),nullptr);
  SendMessageW(h,WM_SETFONT,reinterpret_cast<WPARAM>(font_),TRUE);
  if(std::wstring(cls)!=L"STATIC")SetWindowTheme(h,L"DarkMode_Explorer",nullptr);
  if(group){SetWindowSubclass(h,groupSkin,1,reinterpret_cast<DWORD_PTR>(font_));SetWindowLongPtrW(h,GWL_STYLE,GetWindowLongPtrW(h,GWL_STYLE)|WS_CLIPSIBLINGS);SetWindowPos(h,HWND_BOTTOM,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE);}
  if(std::wstring(cls)==L"BUTTON"&&(style&BS_TYPEMASK)==BS_AUTOCHECKBOX)SetWindowSubclass(h,checkboxSkin,3,reinterpret_cast<DWORD_PTR>(font_));
  if(std::wstring(cls)==L"COMBOBOX")SetWindowSubclass(h,comboSkin,2,0);
  controls_.push_back(h);return h;
}

void ConsoleUI::navigation(){
  SendMessageW(categories_,LB_RESETCONTENT,0,0);navigation_.clear();
  const auto add=[&](const wchar_t* label,int id){SendMessageW(categories_,LB_ADDSTRING,0,reinterpret_cast<LPARAM>(label));navigation_.push_back(id);};
  if(controllerWindow_){add(L"Mandos",8);add(L"Atajos",9);}
  else{
    if(propertiesWindow_)add(L"Resumen",12);
    add(L"Interfaz",0);add(L"BIOS",1);add(L"Consola",2);add(L"Emulación",3);add(L"Memory Cards",4);
    add(L"Gráficos",5);add(L"Mensajes en pantalla",6);add(L"Audio",7);add(L"Captura",11);add(L"Avanzado",10);
  }
  for(size_t row=0;row<navigation_.size();++row)if(navigation_[row]==page_)SendMessageW(categories_,LB_SETCURSEL,row,0);
}

void ConsoleUI::openSettings(int selected){
  const bool controller=selected==8||selected==9;
  const bool gameProperties=selected==12;
  if(settings_&&IsWindow(settings_)){
    apply();controllerWindow_=controller;propertiesWindow_=gameProperties;page_=selected;navigation();page();ShowWindow(settings_,SW_RESTORE);SetForegroundWindow(settings_);return;
  }
  controllerWindow_=controller;propertiesWindow_=gameProperties;
  INITCOMMONCONTROLSEX common{sizeof(common),ICC_TAB_CLASSES|ICC_BAR_CLASSES};InitCommonControlsEx(&common);
  WNDCLASSW wc{};wc.lpfnWndProc=settingsProc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"TM3ConsoleSettings";wc.hCursor=LoadCursor(nullptr,IDC_ARROW);wc.hbrBackground=background_;RegisterClassW(&wc);
  RECT owner{};GetWindowRect(window_,&owner);
  const int x=std::clamp(static_cast<int>(owner.left)+30,0,std::max(0,GetSystemMetrics(SM_CXSCREEN)-1000));
  const int y=std::clamp(static_cast<int>(owner.top)+30,0,std::max(0,GetSystemMetrics(SM_CYSCREEN)-790));
  settings_=CreateWindowExW(WS_EX_CONTROLPARENT,wc.lpszClassName,L"TM3 Online — Ajustes",WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU|WS_CLIPCHILDREN,x,y,1000,760,window_,nullptr,wc.hInstance,this);
  BOOL dark=TRUE;DwmSetWindowAttribute(settings_,20,&dark,sizeof(dark));
  categories_=CreateWindowW(L"LISTBOX",L"",WS_CHILD|WS_VISIBLE|WS_VSCROLL|WS_TABSTOP|LBS_NOTIFY|LBS_OWNERDRAWFIXED|LBS_HASSTRINGS|LBS_NOINTEGRALHEIGHT,12,12,175,535,settings_,reinterpret_cast<HMENU>(401),wc.hInstance,nullptr);
  SendMessageW(categories_,WM_SETFONT,reinterpret_cast<WPARAM>(font_),TRUE);SendMessageW(categories_,LB_SETITEMHEIGHT,0,38);
  pageTitle_=nullptr;
  help_=CreateWindowW(L"STATIC",L"",WS_CHILD|WS_VISIBLE|WS_BORDER|SS_LEFT,12,560,958,100,settings_,reinterpret_cast<HMENU>(402),wc.hInstance,nullptr);
  SendMessageW(pageTitle_,WM_SETFONT,reinterpret_cast<WPARAM>(font_),TRUE);SendMessageW(help_,WM_SETFONT,reinterpret_cast<WPARAM>(font_),TRUE);
  SetWindowSubclass(help_,helpSkin,4,reinterpret_cast<DWORD_PTR>(font_));
  for(const auto& spec:std::initializer_list<std::pair<int,const wchar_t*>>{{306,L"Restablecer valores"},{302,L"Cerrar"}}){
    HWND button=CreateWindowW(L"BUTTON",tm3loc::translate(spec.second).c_str(),WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_OWNERDRAW,spec.first==306?660:860,675,spec.first==306?185:110,34,settings_,reinterpret_cast<HMENU>(static_cast<INT_PTR>(spec.first)),wc.hInstance,nullptr);
    SendMessageW(button,WM_SETFONT,reinterpret_cast<WPARAM>(font_),TRUE);SetWindowTheme(button,L"DarkMode_Explorer",nullptr);
  }
  page_=selected;navigation();page();ShowWindow(settings_,SW_SHOWNORMAL);
}

void ConsoleUI::page(){
  finishBinding(0,true);KillTimer(settings_,601);rebuilding_=true;
  for(auto h:controls_)DestroyWindow(h);controls_.clear();
  SetWindowTextW(settings_,controllerWindow_?L"TM3 Online — Ajustes de mandos":propertiesWindow_?L"TM3 Online — Propiedades del juego":L"TM3 Online — Ajustes");
  SetWindowTextW(pageTitle_,pages[page_]);SetWindowTextW(help_,helpTexts[page_]);
  const auto text=[&](const std::wstring& value,int x,int y,int width,int height,int id=0){return make(L"STATIC",value.c_str(),0,x,y,width,height,id);};
  const auto group=[&](const wchar_t* name,int y,int height){return make(L"BUTTON",name,BS_GROUPBOX,0,y,735,height,0);};
  const auto check=[&](const wchar_t* value,int x,int y,int id,bool on,bool enabled=true){auto h=make(L"BUTTON",value,(enabled?BS_AUTOCHECKBOX:BS_OWNERDRAW)|WS_TABSTOP,x,y,340,28,id);if(enabled)SendMessageW(h,BM_SETCHECK,on?BST_CHECKED:BST_UNCHECKED,0);else SetWindowLongPtrW(h,GWLP_USERDATA,1);EnableWindow(h,enabled);return h;};
  const auto field=[&](const std::wstring& value,int x,int y,int width,int id=0){return make(L"EDIT",value.c_str(),ES_READONLY|WS_BORDER,x,y,width,27,id);};
  const auto combo=[&](int id,int x,int y,int width,const std::initializer_list<const wchar_t*> options,int selected,bool enabled=true){auto h=make(L"COMBOBOX",L"",CBS_DROPDOWNLIST|WS_TABSTOP,x,y,width,200,id);for(auto option:options)SendMessageW(h,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(option));SendMessageW(h,CB_SETCURSEL,selected,0);EnableWindow(h,enabled);return h;};
  switch(page_){
  case 0:
    group(L"Comportamiento",0,105);
    check(L"Confirmar al cerrar el juego",16,30,208,confirmClose_);
    check(L"Doble clic alterna pantalla completa",370,30,209,doubleClick_);
    group(L"Pantalla del juego",120,90);check(L"Iniciar en pantalla completa",16,151,210,startFullscreen_);
    group(L"Apariencia",225,100);text(L"Idioma:",16,260,105,25);combo(219,120,255,215,{L"English",L"Español"},language_);
    text(L"Tema:",370,260,80,25);combo(0,455,255,250,{L"Oscuro"},0,false);
    break;
  case 1:
    group(L"Selección de BIOS",0,190);
    text(tr(L"PS1 BIOS image",L"Imagen BIOS de PS1"),16,35,690,25);
    field(bios_.empty()?tr(L"Automatic / built-in OpenBIOS",L"Automática / OpenBIOS integrado"):bios_.filename().wstring(),16,72,690);
    make(L"BUTTON",tr(L"Choose BIOS...",L"Elegir BIOS..."),BS_PUSHBUTTON|WS_TABSTOP,16,120,215,34,308);
    make(L"BUTTON",tr(L"Use automatic BIOS",L"Usar BIOS automática"),BS_PUSHBUTTON|WS_TABSTOP,245,120,250,34,309);
    text(tr(L"Use a 512 KiB image from your PS1. Choose a BIOS matching the game's region. Applies when the next game is opened.",L"Usa una imagen de 512 KiB de tu PS1 y la región del juego. Se aplica al abrir el siguiente juego."),16,220,690,90);
    break;
  case 2:
    group(L"Consola",0,115);text(L"Región:",16,35,220,25);combo(0,255,30,450,{L"Automática (disco)"},0,false);
    text(L"Memoria principal:",16,74,220,25);field(L"Configuración automática",255,69,450);
    group(L"CPU",135,115);text(L"Modo de ejecución:",16,170,220,25);combo(0,255,165,450,{L"Automático"},0,false);
    group(L"Unidad de CD-ROM",270,90);text(L"Disco:",16,305,90,25);field(game_.empty()?tr(L"No game loaded",L"Sin juego cargado"):game_.stem().wstring(),110,300,595);
    break;
  case 3:
    group(L"Velocidad de emulación",0,115);text(L"Velocidad normal:",16,35,220,25);combo(0,255,30,450,{L"100 % (normal)"},0,false);
    text(L"Frecuencia de emulación:",16,74,220,25);{std::wostringstream rate;rate<<std::fixed<<std::setprecision(2)<<core_.fps()<<L" Hz";field(rate.str(),255,69,450);}
    group(L"Pausa",135,100);text(linked_?L"Pausa del emulador deshabilitada durante el enlace.":L"Sistema > Pausar detiene y continúa la emulación local.",16,170,690,46);
    group(L"CPU",255,90);text(tr(L"TM3 Online: 175% CPU budget. Other PS1 games: standard timing.",L"TM3 Online: presupuesto CPU 175%. Otros juegos PS1: tiempos estándar."),16,287,690,45);
    break;
  case 4:
    for(int slot=0;slot<2;++slot){const int y=slot*145;group(slot==0?L"Tarjeta de memoria 1":L"Tarjeta de memoria 2",y,125);text(L"Tipo de tarjeta:",16,y+35,220,25);combo(0,255,y+30,450,{L"Guardado automático"},0,false);text(L"Directorio:",16,y+78,220,25);field(L"Guardados del jugador",255,y+73,450);}
    make(L"BUTTON",L"Abrir directorio de guardados",BS_PUSHBUTTON,16,322,315,34,304);break;
  case 5:
    group(L"Renderizado",0,110);text(L"Renderizador:",16,35,220,25);combo(0,255,30,450,{L"Software"},0,false);
    text(L"Resolución interna:",16,75,220,25);combo(211,255,70,450,{L"1x (original)",L"2x",L"4x"},resolution_==4?2:resolution_==2?1:0);
    group(L"Presentación",130,155);text(L"Relación de aspecto:",16,165,220,25);combo(202,255,160,450,{L"Automática",L"4:3",L"Estirar a la ventana"},aspect_);
    text(L"Escalado:",16,210,220,25);combo(203,255,205,450,{L"Vecino más cercano",L"Suavizado de presentación"},smooth_?1:0);
    group(L"Mejoras",305,125);check(L"Corrección geométrica PGXP",16,337,216,pgxp_&&!linked_,!linked_);check(L"Renderizado panorámico 16:9",370,337,217,widescreen_&&!linked_,!linked_);text(linked_?L"Mejoras bloqueadas en línea para proteger la sincronización.":L"Opcionales: pueden producir errores visuales según la escena.",16,382,690,30);
    text(tr(L"Deinterlacing",L"Desentrelazado"),16,456,220,25);combo(213,255,450,450,{L"Weave",L"Bob",L"Bob (offset)",L"Motion adaptive",L"Off"},deinterlace_);break;
  case 6:
    group(L"Visualización de información",0,125);check(L"Mostrar estadísticas de rendimiento",16,34,201,stats_);
    text(L"Ubicación:",16,83,220,25);combo(0,255,78,450,{L"Título de la ventana"},0,false);
    group(L"Contadores",145,140);text(L"Velocidad de emulación (FPS).\nNo se muestran datos técnicos ni detalles de conexión.",16,180,690,65);
    break;
  case 7:
    group(L"Controles",0,155);text(L"Volumen de salida:",16,38,200,25);
    {auto slider=make(TRACKBAR_CLASSW,L"",TBS_AUTOTICKS|WS_TABSTOP,220,26,395,42,204);SendMessageW(slider,TBM_SETRANGE,TRUE,MAKELPARAM(0,200));SendMessageW(slider,TBM_SETPOS,TRUE,volume_);}
    text(std::to_wstring(volume_)+L"%",635,38,75,25,207);check(L"Silenciar",16,94,205,muted_);
    group(L"Salida",175,110);text(L"Dispositivo:",16,211,220,25);
    {auto devices=make(L"COMBOBOX",L"",CBS_DROPDOWNLIST|WS_TABSTOP,255,206,450,200,212);SendMessageW(devices,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(L"Predeterminado del sistema"));for(UINT id=0;id<waveOutGetNumDevs();++id){WAVEOUTCAPSW caps{};waveOutGetDevCapsW(id,&caps,sizeof(caps));SendMessageW(devices,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(caps.szPname));}SendMessageW(devices,CB_SETCURSEL,audioDevice_+1,0);}
    group(tr(L"Buffering",L"Búfer de audio"),310,120);text(tr(L"Buffer duration:",L"Duración del búfer:"),16,350,220,25);
    combo(214,255,345,450,{L"20 ms",L"40 ms",L"80 ms"},latency_==20?0:latency_==80?2:1);
    text(tr(L"Windows WaveOut · stereo · 44.1 kHz. Use 80 ms if audio crackles.",L"Windows WaveOut · estéreo · 44.1 kHz. Usa 80 ms si el audio cruje."),16,456,690,40);
    break;
  case 8:
    text(tr(L"PLAYSTATION CONTROLLERS",L"MANDOS PLAYSTATION"),8,0,425,28);
    combo(290,450,-2,275,{tr(L"Player 1 / Port 1",L"Jugador 1 / Puerto 1"),tr(L"Player 2 / Port 2",L"Jugador 2 / Puerto 2")},editingPort_);
    text(tr(L"Each pair: keyboard on the left, controller on the right.",L"Cada pareja: teclado a la izquierda, mando a la derecha."),8,32,710,25);
    {const auto bind=[&](int i,int x,int y){text(buttonNames[i],x,y,170,22);make(L"BUTTON",tm3input::keyName(editingKeys()[i]).c_str(),BS_PUSHBUTTON|WS_TABSTOP,x,y+23,80,28,220+i);make(L"BUTTON",tm3input::padNames[editingPads()[i]],BS_PUSHBUTTON|WS_TABSTOP,x+85,y+23,80,28,260+i);};
    bind(12,8,75);bind(10,190,75);bind(11,380,75);bind(13,562,75);
    for(int i=0;i<4;++i)bind(4+i,8,145+i*62);
    const int action[]={9,1,8,0};for(int i=0;i<4;++i)bind(action[i],562,145+i*62);
    auto diagram=make(L"STATIC",L"PlayStation controller",0,185,151,365,230,281);SetWindowSubclass(diagram,controllerDiagram,7,0);
    bind(14,8,405);bind(2,190,405);bind(3,380,405);bind(15,562,405);}
    check(editingPort_?tr(L"Enable local player 2",L"Activar jugador local 2"):L"Activar mando",8,470,206,editingPort_?secondController_:controller_);combo(218,370,467,355,{tr(L"Automatic (unassigned controller)",L"Automático (mando libre)"),L"Mando 1",L"Mando 2",L"Mando 3",L"Mando 4"},(editingPort_?controllerIndex2_:controllerIndex_)+1);
    text(L"",8,510,720,25,280);SetTimer(settings_,601,50,nullptr);break;
  case 9:{
    group(L"Sistema y vista",0,180);
    const int codes[]={captureKey_,fullscreenKey_,exitKey_};
    for(int row=0;row<3;++row){text(row==0?L"Guardar captura de pantalla":row==1?L"Pantalla completa":L"Cerrar juego",16,37+row*45,360,25);make(L"BUTTON",tm3input::keyName(codes[row]).c_str(),BS_PUSHBUTTON|WS_TABSTOP,400,31+row*45,300,30,240+row);}
    text(L"Pulsa un campo para asignar una tecla. Clic derecho para borrar.",16,210,690,50);SetTimer(settings_,601,50,nullptr);
    break;}
  case 10:
    group(L"Compatibilidad",0,125);text(L"La configuración de compatibilidad se aplica automáticamente.\nNo necesitas modificar opciones técnicas para jugar.",16,38,690,65);break;
  case 11:
    group(L"Capturas de pantalla",0,170);text(L"Formato:",16,38,220,25);combo(0,255,33,450,{L"BMP (sin pérdida)"},0,false);
    text(L"Directorio:",16,85,220,25);field(L"Capturas del jugador",255,80,450);make(L"BUTTON",L"Abrir...",BS_PUSHBUTTON,570,122,135,32,307);
    break;
  case 12:
    group(L"Información del juego",0,145);text(L"Título:",16,40,120,25);field(game_.empty()?tr(L"No game loaded",L"Sin juego cargado"):game_.stem().wstring(),145,35,560);text(L"Consola:",16,90,120,25);field(L"PlayStation",145,85,560);break;
  }
  // Group boxes are siblings of their fields, not containers. Keep them behind
  // every field after constructing the page, so repaint cannot cover controls.
  for(auto h:controls_){wchar_t cls[32]{};GetClassNameW(h,cls,32);if(std::wstring(cls)==L"Button"&&(GetWindowLongPtrW(h,GWL_STYLE)&BS_TYPEMASK)==BS_GROUPBOX)SetWindowPos(h,HWND_BOTTOM,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE);}
  RedrawWindow(settings_,nullptr,nullptr,RDW_INVALIDATE|RDW_ALLCHILDREN|RDW_UPDATENOW);
  rebuilding_=false;
}

void ConsoleUI::bindingLabels(){
  for(int i=0;i<16;++i){SetDlgItemTextW(settings_,220+i,tm3input::keyName(editingKeys()[i]).c_str());SetDlgItemTextW(settings_,260+i,tm3input::padNames[editingPads()[i]]);}
  const int shortcuts[]={captureKey_,fullscreenKey_,exitKey_};for(int i=0;i<3;++i)SetDlgItemTextW(settings_,240+i,tm3input::keyName(shortcuts[i]).c_str());
}
void ConsoleUI::beginBinding(int id){
  if(captureId_==id){finishBinding(0,true);return;}finishBinding(0,true);captureId_=id;captureDeadline_=GetTickCount64()+15000;
  previousPad_=capturePadMask();SetDlgItemTextW(settings_,id,L"Pulsa...");SetFocus(GetDlgItem(settings_,id));
  SetWindowTextW(help_,id>=260?L"Pulsa un botón o mueve una palanca del mando. Esc cancela.":L"Pulsa la tecla que quieres asignar, incluidas flechas, espacio, Tab y teclas de función. Esc cancela.");
}
void ConsoleUI::finishBinding(int value,bool cancel){
  if(!captureId_)return;const int id=captureId_;captureId_=0;
  if(!cancel){
    if(id>=260&&id<276)editingPads()[id-260]=std::clamp(value,0,24);
    else if(id>=240&&id<=242){int* shortcuts[]={&captureKey_,&fullscreenKey_,&exitKey_};*shortcuts[id-240]=std::clamp(value,0,255);}
    else if(id>=220&&id<236){editingKeys()[id-220]=std::clamp(value,0,255);if(value){if(captureKey_==value)captureKey_=0;if(fullscreenKey_==value)fullscreenKey_=0;if(exitKey_==value)exitKey_=0;}}
    updateCore();save();
  }
  bindingLabels();SetWindowTextW(help_,helpTexts[page_]);
}
void ConsoleUI::pollPadCapture(uint32_t mask){
  if(captureId_&&GetTickCount64()>=captureDeadline_){finishBinding(0,true);return;}
  const uint32_t edge=mask&~previousPad_;previousPad_=mask;
  if(captureId_>=260&&edge)for(int id=1;id<=24;++id)if(edge&(1u<<id)){finishBinding(id);break;}
}
uint32_t ConsoleUI::capturePadMask() const{
  const auto pair=tm3input::readPair(controller_?controllerIndex_:-2,(secondController_||editingPort_)?controllerIndex2_:-2);
  return pair[editingPort_].mask;
}

void ConsoleUI::apply(){
  if(rebuilding_)return;
  const auto checked=[&](int id){return SendDlgItemMessageW(settings_,id,BM_GETCHECK,0,0)==BST_CHECKED;};
  const int oldLanguage=language_;
  if(page_==0){confirmClose_=checked(208);doubleClick_=checked(209);startFullscreen_=checked(210);language_=SendDlgItemMessageW(settings_,219,CB_GETCURSEL,0,0)==1?1:0;}
  if(page_==6)stats_=checked(201);
  if(page_==5){const int index=static_cast<int>(SendDlgItemMessageW(settings_,211,CB_GETCURSEL,0,0));resolution_=index==2?4:index==1?2:1;if(!linked_){pgxp_=checked(216);widescreen_=checked(217);}aspect_=static_cast<int>(SendDlgItemMessageW(settings_,202,CB_GETCURSEL,0,0));smooth_=SendDlgItemMessageW(settings_,203,CB_GETCURSEL,0,0)==1;InvalidateRect(window_,nullptr,TRUE);}
  if(page_==5)deinterlace_=std::clamp(static_cast<int>(SendDlgItemMessageW(settings_,213,CB_GETCURSEL,0,0)),0,4);
  if(page_==7){volume_=static_cast<int>(SendDlgItemMessageW(settings_,204,TBM_GETPOS,0,0));muted_=checked(205);audioDevice_=static_cast<int>(SendDlgItemMessageW(settings_,212,CB_GETCURSEL,0,0))-1;const auto value=std::to_wstring(volume_)+L"%";SetDlgItemTextW(settings_,207,value.c_str());const int latency=static_cast<int>(SendDlgItemMessageW(settings_,214,CB_GETCURSEL,0,0));latency_=latency==0?20:latency==2?80:40;}
  if(page_==8){const int index=static_cast<int>(SendDlgItemMessageW(settings_,218,CB_GETCURSEL,0,0))-1;if(editingPort_){secondController_=checked(206);controllerIndex2_=index;}else{controller_=checked(206);controllerIndex_=index;}}
  updateCore();save();if(oldLanguage!=language_)refreshLanguage();
}

void ConsoleUI::defaults(){
  if(MessageBoxW(settings_,L"¿Restablecer los ajustes locales de esta consola?",L"Restablecer valores",MB_YESNO|MB_ICONQUESTION)!=IDYES)return;
  aspect_=0;volume_=100;smooth_=false;muted_=false;stats_=false;controller_=true;confirmClose_=false;doubleClick_=true;startFullscreen_=false;
  resolution_=1;pgxp_=false;widescreen_=false;audioDevice_=-1;controllerIndex_=-1;secondController_=false;controllerIndex2_=-1;keys2_=tm3keyboard::keys2;pads2_=tm3input::pads;captureKey_=VK_F10;fullscreenKey_=VK_F11;exitKey_=VK_ESCAPE;keys_=tm3keyboard::keys;pads_=tm3input::pads;updateCore();save();page();
}

LRESULT CALLBACK ConsoleUI::settingsProc(HWND h,UINT message,WPARAM w,LPARAM l){
  auto* self=reinterpret_cast<ConsoleUI*>(GetWindowLongPtrW(h,GWLP_USERDATA));
  if(message==WM_NCCREATE){self=static_cast<ConsoleUI*>(reinterpret_cast<CREATESTRUCTW*>(l)->lpCreateParams);SetWindowLongPtrW(h,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(self));}
  if(!self)return DefWindowProcW(h,message,w,l);
  if(self->draw(message,l))return TRUE;
  if(message==WM_ERASEBKGND){RECT rect;GetClientRect(h,&rect);FillRect(reinterpret_cast<HDC>(w),&rect,self->background_);return 1;}
  if(message==WM_CTLCOLORSTATIC||message==WM_CTLCOLORBTN||message==WM_CTLCOLORLISTBOX||message==WM_CTLCOLOREDIT){const auto dc=reinterpret_cast<HDC>(w);SetTextColor(dc,RGB(235,235,235));SetBkColor(dc,RGB(22,29,41));return reinterpret_cast<LRESULT>(self->background_);}
  if(message==WM_HSCROLL&&self->page_==7){self->volume_=static_cast<int>(SendDlgItemMessageW(h,204,TBM_GETPOS,0,0));self->core_.setVolume(self->volume_);const auto value=std::to_wstring(self->volume_)+L"%";SetDlgItemTextW(h,207,value.c_str());if(LOWORD(w)==TB_ENDTRACK)self->save();return 0;}
  if(message==WM_COMMAND){
    const int id=LOWORD(w),event=HIWORD(w);
    if(id==290&&event==CBN_SELCHANGE&&!self->rebuilding_){const int port=static_cast<int>(SendDlgItemMessageW(h,290,CB_GETCURSEL,0,0));self->finishBinding(0,true);self->apply();self->editingPort_=port==1?1:0;self->page();return 0;}
    if(event==BN_CLICKED&&((self->page_==8&&((id>=220&&id<236)||(id>=260&&id<276)))||(self->page_==9&&id>=240&&id<=242))){self->beginBinding(id);return 0;}
    if(id==401&&event==LBN_SELCHANGE){const int row=static_cast<int>(SendMessageW(self->categories_,LB_GETCURSEL,0,0));if(row>=0&&static_cast<size_t>(row)<self->navigation_.size()&&self->navigation_[row]>=0){self->apply();self->page_=self->navigation_[row];self->page();}else{for(size_t i=0;i<self->navigation_.size();++i)if(self->navigation_[i]==self->page_)SendMessageW(self->categories_,LB_SETCURSEL,i,0);}return 0;}
    if(!self->rebuilding_&&id>=201&&id<=242&&(event==BN_CLICKED||event==CBN_SELCHANGE||event==EN_KILLFOCUS)){self->apply();return 0;}
    switch(id){case 308:self->selectBios();return 0;case 309:self->bios_.clear();self->save();self->page();return 0;case 301:self->apply();return 0;case IDCANCEL:case 302:SendMessageW(h,WM_CLOSE,0,0);return 0;case 304:self->folder(self->core_.saveDirectory());return 0;case 306:self->defaults();return 0;case 307:self->folder(self->base_/L"captures");return 0;}
  }
  if(message==WM_TIMER&&w==601){const auto pair=tm3input::readPair(self->controller_?self->controllerIndex_:-2,(self->secondController_||self->editingPort_)?self->controllerIndex2_:-2);const auto pad=pair[self->editingPort_];SetDlgItemTextW(h,280,pad.connected?L"Mando conectado":L"Sin mando conectado — el teclado sigue disponible");self->pollPadCapture(pad.mask);return 0;}
  if(message==WM_ACTIVATE&&LOWORD(w)==WA_INACTIVE)self->finishBinding(0,true);
  if(message==WM_CONTEXTMENU){const int id=GetDlgCtrlID(reinterpret_cast<HWND>(w));if((self->page_==8&&((id>=220&&id<236)||(id>=260&&id<276)))||(self->page_==9&&id>=240&&id<=242)){self->finishBinding(0,true);self->beginBinding(id);self->finishBinding(0);return 0;}}
  if(message==WM_CLOSE){self->finishBinding(0,true);self->apply();self->rebuilding_=true;DestroyWindow(h);self->settings_=nullptr;self->categories_=nullptr;self->help_=nullptr;self->pageTitle_=nullptr;self->controls_.clear();self->rebuilding_=false;return 0;}
  return DefWindowProcW(h,message,w,l);
}
