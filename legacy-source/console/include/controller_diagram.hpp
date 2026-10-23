#pragma once
#include <windows.h>
// Original vector drawing: no external asset, bitmap scaling or font dependency.
inline LRESULT CALLBACK controllerDiagram(HWND h,UINT msg,WPARAM w,LPARAM l,UINT_PTR id,DWORD_PTR){
 if(msg==WM_PAINT){
  PAINTSTRUCT ps{};HDC dc=BeginPaint(h,&ps);RECT r{};GetClientRect(h,&r);
  HBRUSH bg=CreateSolidBrush(RGB(25,31,42));FillRect(dc,&r,bg);DeleteObject(bg);
  SetGraphicsMode(dc,GM_ADVANCED);XFORM scale{r.right/360.0f,0,0,r.bottom/240.0f,0,0};SetWorldTransform(dc,&scale);
  HPEN pen=CreatePen(PS_SOLID,2,RGB(20,23,30));auto oldPen=SelectObject(dc,pen);
  HBRUSH shell=CreateSolidBrush(RGB(179,186,198));auto oldBrush=SelectObject(dc,shell);
  POINT outline[]={{58,42},{105,34},{132,70},{228,70},{255,34},{302,42},{326,88},{344,202},{324,222},{297,222},{254,175},{106,175},{63,222},{36,222},{16,202},{34,88}};
  Polygon(dc,outline,16);RoundRect(dc,42,26,104,61,12,12);RoundRect(dc,256,26,318,61,12,12);
  HBRUSH face=CreateSolidBrush(RGB(207,212,220));SelectObject(dc,face);Ellipse(dc,32,66,132,166);Ellipse(dc,228,66,328,166);
  HBRUSH dark=CreateSolidBrush(RGB(67,75,88));SelectObject(dc,dark);
  POINT cross[]={{70,83},{94,83},{94,105},{115,105},{115,127},{94,127},{94,150},{70,150},{70,127},{48,127},{48,105},{70,105}};Polygon(dc,cross,12);
  Ellipse(dc,98,145,160,207);Ellipse(dc,200,145,262,207);RoundRect(dc,145,110,166,123,4,4);
  POINT start[]={{194,109},{194,125},{214,117}};Polygon(dc,start,3);
  const int xs[]={278,306,278,250},ys[]={91,117,143,117};
  for(int i=0;i<4;++i){SelectObject(dc,dark);Ellipse(dc,xs[i]-14,ys[i]-14,xs[i]+14,ys[i]+14);}
  const COLORREF colors[]={RGB(87,220,174),RGB(244,122,136),RGB(126,175,255),RGB(220,151,228)};
  for(int i=0;i<4;++i){HPEN symbol=CreatePen(PS_SOLID,2,colors[i]);SelectObject(dc,symbol);SelectObject(dc,GetStockObject(HOLLOW_BRUSH));int x=xs[i],y=ys[i];
   if(i==0){POINT triangle[]={{x,y-8},{x-8,y+7},{x+8,y+7},{x,y-8}};Polyline(dc,triangle,4);}
   if(i==1)Ellipse(dc,x-8,y-8,x+8,y+8);
   if(i==2){MoveToEx(dc,x-6,y-6,nullptr);LineTo(dc,x+6,y+6);MoveToEx(dc,x+6,y-6,nullptr);LineTo(dc,x-6,y+6);}
   if(i==3)Rectangle(dc,x-7,y-7,x+7,y+7);
   SelectObject(dc,pen);DeleteObject(symbol);
  }
  SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(40,47,60));HFONT font=CreateFontW(-10,0,0,0,FW_BOLD,0,0,0,DEFAULT_CHARSET,0,0,ANTIALIASED_QUALITY,0,L"Segoe UI");auto oldFont=SelectObject(dc,font);
  RECT label{135,128,222,144};DrawTextW(dc,L"SELECT    START",-1,&label,DT_CENTER|DT_SINGLELINE);
  SelectObject(dc,oldFont);DeleteObject(font);SelectObject(dc,oldBrush);SelectObject(dc,oldPen);DeleteObject(shell);DeleteObject(face);DeleteObject(dark);DeleteObject(pen);EndPaint(h,&ps);return 0;
 }
 if(msg==WM_NCDESTROY)RemoveWindowSubclass(h,controllerDiagram,id);
 return DefSubclassProc(h,msg,w,l);
}
