#include "video_buffer.hpp"
#include <cstdio>
int main(){
  HDC target=CreateCompatibleDC(nullptr);
  BITMAPINFO bi{};bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
  bi.bmiHeader.biWidth=32;bi.bmiHeader.biHeight=-32;
  bi.bmiHeader.biPlanes=1;bi.bmiHeader.biBitCount=32;bi.bmiHeader.biCompression=BI_RGB;
  void* pixels=nullptr;
  HBITMAP bitmap=CreateDIBSection(target,&bi,DIB_RGB_COLORS,&pixels,nullptr,0);
  if(!target||!bitmap)return 1;
  HGDIOBJ previous=SelectObject(target,bitmap);
  int result=0;
  {
    VideoBuffer buffer;
    if(buffer.prepare(target,0,32))result=2;
    for(int i=0;i<100&&!result;++i){
      int size=(i%2)?16:32;
      HDC back=buffer.prepare(target,size,size);
      if(!back){result=3;break;}
      RECT r{0,0,size,size};HBRUSH brush=CreateSolidBrush(RGB(255,0,0));
      FillRect(back,&r,brush);DeleteObject(brush);
      if(!buffer.present(target)||GetPixel(target,0,0)!=RGB(255,0,0))result=4;
      if(buffer.prepare(target,size,size)!=back)result=5;
    }
    buffer.reset();buffer.reset();
    if(buffer.present(target))result=6;
  }
  SelectObject(target,previous);DeleteObject(bitmap);DeleteDC(target);
  std::printf("video buffer test result=%d\n",result);return result;
}
