#include "core_host.hpp"
#include <Xinput.h>
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>

CoreHost* CoreHost::instance=nullptr;
bool CoreHost::load(const std::filesystem::path& core,const std::filesystem::path& game,const std::filesystem::path& base){
  instance=this;base_=base;systemDir_=(base/"system").string();saveDir_=(saveSlot_.empty()?base/"saves":base/("saves_"+saveSlot_)).string();contentDir_=game.parent_path().string();
  std::filesystem::create_directories(saveDir_);dll_=LoadLibraryW(core.c_str());if(!dll_)return false;
#define S(n) if(!sym(n,#n))return false
  S(retro_api_version);S(retro_init);S(retro_deinit);S(retro_get_system_info);S(retro_get_system_av_info);S(retro_set_environment);S(retro_set_video_refresh);S(retro_set_audio_sample);S(retro_set_audio_sample_batch);S(retro_set_input_poll);S(retro_set_input_state);S(retro_set_controller_port_device);S(retro_run);S(retro_load_game);S(retro_unload_game);S(retro_get_memory_data);S(retro_get_memory_size);
#undef S
  if(retro_api_version()!=RETRO_API_VERSION)return false;
  retro_set_environment(env);retro_set_video_refresh(video);retro_set_audio_sample(sample);retro_set_audio_sample_batch(samples);retro_set_input_poll(inputPoll);retro_set_input_state(inputState);retro_init();
  retro_system_info si{};retro_get_system_info(&si);std::string gamePath=game.string();retro_game_info gi{gamePath.c_str(),nullptr,0,nullptr};if(!retro_load_game(&gi))return false;
  retro_set_controller_port_device(0,RETRO_DEVICE_JOYPAD);retro_get_system_av_info(&av_);audio_.open((unsigned)av_.timing.sample_rate);
  net_.poll(static_cast<uint8_t*>(retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)),retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM));return true;
}
void CoreHost::unload(){if(dll_){retro_unload_game();retro_deinit();FreeLibrary(dll_);dll_=nullptr;}instance=nullptr;}
void CoreHost::runFrame(){retro_run();auto* p=(uint8_t*)retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM);auto n=retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM);net_.poll(p,n);}
bool CoreHost::env(unsigned cmd,void* data){auto& s=*instance;switch(cmd){
 case RETRO_ENVIRONMENT_GET_CAN_DUPE:*static_cast<bool*>(data)=true;return true;
 case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:*static_cast<const char**>(data)=s.systemDir_.c_str();return true;
 case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:*static_cast<const char**>(data)=s.saveDir_.c_str();return true;
 case RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY:*static_cast<const char**>(data)=s.systemDir_.c_str();return true;
 case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:s.format_=*static_cast<retro_pixel_format*>(data);return true;
 case RETRO_ENVIRONMENT_SET_VARIABLES:{auto* v=(retro_variable*)data;for(;v&&v->key;v++){std::string x=v->value?v->value:"";auto p=x.find(';');if(p!=std::string::npos){x=x.substr(p+1);while(!x.empty()&&x.front()==' ')x.erase(x.begin());auto q=x.find('|');if(q!=std::string::npos)x.resize(q);}s.vars_[v->key]=x;}return true;}
 case RETRO_ENVIRONMENT_GET_VARIABLE:{auto* v=(retro_variable*)data;auto it=s.vars_.find(v->key?v->key:"");v->value=it==s.vars_.end()?nullptr:it->second.c_str();return true;}
 case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:*static_cast<bool*>(data)=false;return true;
 case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:static_cast<retro_log_callback*>(data)->log=log;return true;
 case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:return true;
 case RETRO_ENVIRONMENT_GET_LANGUAGE:*static_cast<unsigned*>(data)=0;return true;
 case RETRO_ENVIRONMENT_SHUTDOWN:PostQuitMessage(0);return true;
 case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:return true;
 default:return false;}}
void CoreHost::video(const void* data,unsigned w,unsigned h,size_t pitch){
  auto& s=*instance;
  // Libretro uses (void*)-1 as a sentinel when a hardware-rendered frame is
  // valid. This frontend only supports software frames, so never dereference it.
  const auto address=reinterpret_cast<uintptr_t>(data);
  if(!data||address==~uintptr_t{0}||!w||!h)return;

  const size_t bytesPerPixel=s.format_==RETRO_PIXEL_FORMAT_XRGB8888?4u:2u;
  if(static_cast<size_t>(w)>SIZE_MAX/bytesPerPixel||
     pitch<static_cast<size_t>(w)*bytesPerPixel||
     static_cast<size_t>(h)>SIZE_MAX/static_cast<size_t>(w))return;

  std::scoped_lock frameLock(s.frameMutex_);
  if(s.width_!=w||s.height_!=h||s.pitch_!=pitch){
    char message[192]{};
    std::snprintf(message,sizeof(message),
      "TM3Online video: format=%u width=%u height=%u pitch=%zu packed=%zu\n",
      static_cast<unsigned>(s.format_),w,h,pitch,
      static_cast<size_t>(w)*bytesPerPixel);
    std::fputs(message,stderr);
    OutputDebugStringA(message);
  }

  s.frame32_.resize(static_cast<size_t>(w)*h);
  const auto* source=static_cast<const uint8_t*>(data);
  for(unsigned y=0;y<h;++y){
    const auto* sourceRow=source+static_cast<size_t>(y)*pitch;
    auto* destination=s.frame32_.data()+static_cast<size_t>(y)*w;
    if(s.format_==RETRO_PIXEL_FORMAT_XRGB8888){
      const auto* pixels=reinterpret_cast<const uint32_t*>(sourceRow);
      for(unsigned x=0;x<w;++x)destination[x]=pixels[x]&0x00FFFFFFu;
    }else{
      const auto* pixels=reinterpret_cast<const uint16_t*>(sourceRow);
      for(unsigned x=0;x<w;++x){
        const uint16_t pixel=pixels[x];
        uint32_t r5,g5,b5,g8;
        if(s.format_==RETRO_PIXEL_FORMAT_RGB565){
          r5=(pixel>>11)&0x1Fu;
          const uint32_t g6=(pixel>>5)&0x3Fu;
          b5=pixel&0x1Fu;
          g8=(g6<<2)|(g6>>4);
        }else{
          r5=(pixel>>10)&0x1Fu;
          g5=(pixel>>5)&0x1Fu;
          b5=pixel&0x1Fu;
          g8=(g5<<3)|(g5>>2);
        }
        const uint32_t r8=(r5<<3)|(r5>>2);
        const uint32_t b8=(b5<<3)|(b5>>2);
        destination[x]=(r8<<16)|(g8<<8)|b8;
      }
    }
  }
  s.width_=w;s.height_=h;s.pitch_=pitch;
}
void CoreHost::sample(int16_t l,int16_t r){int16_t x[2]{l,r};instance->audio_.push(x,1);}size_t CoreHost::samples(const int16_t* p,size_t n){instance->audio_.push(p,n);return n;}
void CoreHost::inputPoll(){instance->pollInput();}
void CoreHost::pollInput(){buttons_.fill(0);if(!inputEnabled_.load(std::memory_order_acquire))return;XINPUT_STATE x{};if(XInputGetState(0,&x)==ERROR_SUCCESS){auto b=x.Gamepad.wButtons;buttons_[RETRO_DEVICE_ID_JOYPAD_A]=!!(b&XINPUT_GAMEPAD_A);buttons_[RETRO_DEVICE_ID_JOYPAD_B]=!!(b&XINPUT_GAMEPAD_B);buttons_[RETRO_DEVICE_ID_JOYPAD_X]=!!(b&XINPUT_GAMEPAD_X);buttons_[RETRO_DEVICE_ID_JOYPAD_Y]=!!(b&XINPUT_GAMEPAD_Y);buttons_[RETRO_DEVICE_ID_JOYPAD_START]=!!(b&XINPUT_GAMEPAD_START);buttons_[RETRO_DEVICE_ID_JOYPAD_SELECT]=!!(b&XINPUT_GAMEPAD_BACK);buttons_[RETRO_DEVICE_ID_JOYPAD_UP]=!!(b&XINPUT_GAMEPAD_DPAD_UP);buttons_[RETRO_DEVICE_ID_JOYPAD_DOWN]=!!(b&XINPUT_GAMEPAD_DPAD_DOWN);buttons_[RETRO_DEVICE_ID_JOYPAD_LEFT]=!!(b&XINPUT_GAMEPAD_DPAD_LEFT);buttons_[RETRO_DEVICE_ID_JOYPAD_RIGHT]=!!(b&XINPUT_GAMEPAD_DPAD_RIGHT);buttons_[RETRO_DEVICE_ID_JOYPAD_L]=!!(b&XINPUT_GAMEPAD_LEFT_SHOULDER);buttons_[RETRO_DEVICE_ID_JOYPAD_R]=!!(b&XINPUT_GAMEPAD_RIGHT_SHOULDER);}else{buttons_[RETRO_DEVICE_ID_JOYPAD_UP]=!!(GetAsyncKeyState(VK_UP)&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_DOWN]=!!(GetAsyncKeyState(VK_DOWN)&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_LEFT]=!!(GetAsyncKeyState(VK_LEFT)&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_RIGHT]=!!(GetAsyncKeyState(VK_RIGHT)&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_A]=!!(GetAsyncKeyState('X')&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_B]=!!(GetAsyncKeyState('C')&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_X]=!!(GetAsyncKeyState('S')&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_Y]=!!(GetAsyncKeyState('D')&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_START]=!!(GetAsyncKeyState(VK_RETURN)&0x8000);buttons_[RETRO_DEVICE_ID_JOYPAD_SELECT]=!!(GetAsyncKeyState(VK_RSHIFT)&0x8000);}}
int16_t CoreHost::inputState(unsigned port,unsigned device,unsigned,unsigned id){if(port||device!=RETRO_DEVICE_JOYPAD)return 0;if(id==RETRO_DEVICE_ID_JOYPAD_MASK){uint16_t m=0;for(unsigned i=0;i<16;i++)if(instance->buttons_[i])m|=1u<<i;return (int16_t)m;}return id<16?instance->buttons_[id]:0;}
void CoreHost::log(int,const char* fmt,...){va_list a;va_start(a,fmt);vfprintf(stderr,fmt,a);va_end(a);}
void CoreHost::paint(HDC dc,const RECT& dst){
  std::scoped_lock frameLock(frameMutex_);
  if(!width_||!height_||frame32_.size()!=static_cast<size_t>(width_)*height_)return;
  BITMAPINFO bi{};
  bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
  bi.bmiHeader.biWidth=(LONG)width_;
  bi.bmiHeader.biHeight=-(LONG)height_;
  bi.bmiHeader.biPlanes=1;
  bi.bmiHeader.biBitCount=32;
  bi.bmiHeader.biCompression=BI_RGB;
  bi.bmiHeader.biSizeImage=static_cast<DWORD>(frame32_.size()*sizeof(uint32_t));
  int dw=dst.right-dst.left,dh=dst.bottom-dst.top;double ar=av_.geometry.aspect_ratio>0?av_.geometry.aspect_ratio:(double)width_/height_;int w=dw,h=(int)(w/ar);if(h>dh){h=dh;w=(int)(h*ar);}int x=(dw-w)/2,y=(dh-h)/2;SetStretchBltMode(dc,COLORONCOLOR);StretchDIBits(dc,x,y,w,h,0,0,width_,height_,frame32_.data(),&bi,DIB_RGB_COLORS,SRCCOPY);
}
