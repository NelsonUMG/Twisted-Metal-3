#pragma once
#include <windows.h>

// UI-thread-only backing surface. Never exposes the black clearing pass.
class VideoBuffer {
  HDC dc_{};
  HBITMAP bitmap_{};
  HGDIOBJ original_{};
  int width_{},height_{};
public:
  VideoBuffer()=default;
  VideoBuffer(const VideoBuffer&)=delete;
  VideoBuffer& operator=(const VideoBuffer&)=delete;
  ~VideoBuffer(){reset();}
  void reset(){
    if(dc_&&original_)SelectObject(dc_,original_);
    if(bitmap_)DeleteObject(bitmap_);
    if(dc_)DeleteDC(dc_);
    dc_=nullptr;bitmap_=nullptr;original_=nullptr;width_=height_=0;
  }
  HDC prepare(HDC target,int width,int height){
    if(width<=0||height<=0)return nullptr;
    if(dc_&&width==width_&&height==height_)return dc_;
    HDC next=CreateCompatibleDC(target);
    if(!next)return nullptr;
    HBITMAP bitmap=CreateCompatibleBitmap(target,width,height);
    if(!bitmap){DeleteDC(next);return nullptr;}
    HGDIOBJ original=SelectObject(next,bitmap);
    if(!original||original==HGDI_ERROR){DeleteObject(bitmap);DeleteDC(next);return nullptr;}
    reset();dc_=next;bitmap_=bitmap;original_=original;width_=width;height_=height;
    return dc_;
  }
  bool present(HDC target){return dc_&&BitBlt(target,0,0,width_,height_,dc_,0,0,SRCCOPY)!=0;}
};
