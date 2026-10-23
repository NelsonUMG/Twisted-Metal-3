#include "core_host.hpp"
#include "keyboard_bindings.hpp"
#include "input_bindings.hpp"
#include "diagnostics_mode.hpp"
#include <Xinput.h>
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>

CoreHost* CoreHost::instance=nullptr;
bool CoreHost::load(const std::filesystem::path& core,const std::filesystem::path& game,const std::filesystem::path& base){
  if(dll_)unload();
  vars_.clear();resetRequested_.store(false);optionsChanged_=false;linkedReady_.store(false);
  returningMenu_=false;previousTriangle_=false;menuReturnRequested_.store(false);menuReturned_.store(false);menuReturnFailed_.store(false);
  tm3Content_=game.filename()==L"TM3_SQRT_MERGE_V4.cue";
  SetEnvironmentVariableW(L"TM3O_STANDARD_PS1",tm3Content_?L"0":L"1");
  wchar_t bios[32768]{};GetPrivateProfileStringW(L"Console",L"BIOS",L"",bios,32768,(base/L"TM3Console.ini").c_str());
  const std::filesystem::path biosFile=bios;
  const auto selected=biosFile.is_absolute()?biosFile:base/biosFile;
  const auto utf=selected.u8string();const std::string biosUtf(utf.begin(),utf.end());
  _putenv_s("TM3O_BIOS_PATH",bios[0]?biosUtf.c_str():"");
  for(unsigned i=0;i<16;++i){keys_[i].store(tm3keyboard::keys[i]);padBindings_[i].store(tm3input::pads[i]);keys2_[i].store(tm3keyboard::keys2[i]);padBindings2_[i].store(tm3input::pads[i]);}
  secondController_.store(GetPrivateProfileIntW(L"Console",L"Player2Enabled",0,(base/L"TM3Console.ini").c_str())!=0);
  videoFrames_.reset();instance=this;base_=base;systemDir_=(base/"system").string();saveDir_=(saveSlot_.empty()?base/"saves":base/("saves_"+saveSlot_)).string();contentDir_=game.parent_path().string();
  std::filesystem::create_directories(saveDir_);dll_=LoadLibraryW(core.c_str());if(!dll_)return false;
#define S(n) if(!sym(n,#n)){unload();return false;}
  S(retro_api_version);S(retro_init);S(retro_deinit);S(retro_get_system_info);S(retro_get_system_av_info);S(retro_set_environment);S(retro_set_video_refresh);S(retro_set_audio_sample);S(retro_set_audio_sample_batch);S(retro_set_input_poll);S(retro_set_input_state);S(retro_set_controller_port_device);S(retro_run);S(retro_reset);S(retro_load_game);S(retro_unload_game);S(retro_get_memory_data);S(retro_get_memory_size);
#undef S
  if(retro_api_version()!=RETRO_API_VERSION){unload();return false;}
  retro_set_environment(env);retro_set_video_refresh(video);retro_set_audio_sample(sample);retro_set_audio_sample_batch(samples);retro_set_input_poll(inputPoll);retro_set_input_state(inputState);retro_init();initialized_=true;
  retro_system_info si{};retro_get_system_info(&si);const auto pathUtf=game.u8string();std::string gamePath(pathUtf.begin(),pathUtf.end());retro_game_info gi{gamePath.c_str(),nullptr,0,nullptr};if(!retro_load_game(&gi)){unload();return false;}loaded_.store(true);
  retro_set_controller_port_device(0,RETRO_DEVICE_JOYPAD);retro_set_controller_port_device(1,secondController_.load()?RETRO_DEVICE_JOYPAD:0);secondPortChanged_.store(false);retro_get_system_av_info(&av_);reportedFps_.store(av_.timing.fps>1?av_.timing.fps:60.0);displayAspect_.store(av_.geometry.aspect_ratio>0?av_.geometry.aspect_ratio:4.0/3.0);audio_.open((unsigned)av_.timing.sample_rate);
  if(tm3DiagnosticsEnabled())perfFile_.open(base/((saveSlot_.empty()?std::string("local"):saveSlot_)+".host_performance.csv"));
  if(perfFile_)perfFile_<<"elapsed_s,window_s,core_frames,core_frames_per_s,core_ms_mean,core_ms_p95,core_ms_max,net_poll_ms_mean,net_poll_ms_max,frame_interval_ms_p95,frame_interval_ms_max,video_callbacks,video_callback_ms,paint_calls,paint_ms,time_steps,time_discontinuities,batch_pending_samples,requests_total,completed_total\n";
  perfStart_=perfWindowStart_=PerfClock::now();
  if(tm3Content_)net_->poll(static_cast<uint8_t*>(retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)),retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM));return true;
}
void CoreHost::unload(){if(dll_){if(loaded_.exchange(false))retro_unload_game();if(initialized_)retro_deinit();initialized_=false;FreeLibrary(dll_);dll_=nullptr;}audio_.close();videoFrames_.reset();perfFile_.close();instance=nullptr;}
void CoreHost::setGraphics(int resolution,bool pgxp,bool widescreen){
  if(resolution!=1&&resolution!=2&&resolution!=4)resolution=1;
  std::scoped_lock lock(optionMutex_);resolution_.store(resolution);
  for(const auto* prefix:{"beetle_psx_","beetle_psx_hw_"}){const std::string key=prefix;pendingOptions_[key+"internal_resolution"]=resolution==1?"1x(native)":std::to_string(resolution)+"x";pendingOptions_[key+"pgxp_mode"]=pgxp?"memory only":"disabled";pendingOptions_[key+"widescreen_hack"]=widescreen?"enabled":"disabled";pendingOptions_[key+"widescreen_hack_aspect_ratio"]="16:9";}
}
void CoreHost::runFrame(){
  if(!loaded())return;
  if(secondPortChanged_.exchange(false))retro_set_controller_port_device(1,secondController_.load()?RETRO_DEVICE_JOYPAD:0);
  if(menuReturnRequested_.exchange(false)){returningMenu_=true;returnMenuFrame_=0;}
  if(returningMenu_&&menuTable_.load()==0x8007FEDC){returningMenu_=false;menuReturned_.store(true);}
  {std::scoped_lock lock(optionMutex_);for(const auto& [key,value]:pendingOptions_)if(auto found=vars_.find(key);found!=vars_.end()&&found->second!=value){found->second=value;optionsChanged_=true;}pendingOptions_.clear();}
  auto* p=(uint8_t*)retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM);
  auto n=retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM);
  const auto start=PerfClock::now();
  if(tm3Content_)net_->poll(p,n);
  const auto beforeCore=PerfClock::now();
  if(resetRequested_.exchange(false))retro_reset();
  retro_run();
  const auto afterCore=PerfClock::now();
  p=(uint8_t*)retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM);
  n=retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM);
  if(tm3Content_)net_->poll(p,n);
  const auto end=PerfClock::now();
  if(tm3Content_&&p&&n>0x4790C){
    uint32_t magic=0;uint16_t flags=0;std::memcpy(&magic,p+0x47900,4);std::memcpy(&flags,p+0x4790A,2);
    linkedReady_.store(magic==0x4F334D54&&(flags&0x100)!=0);
    mailboxMagic_.store(magic);
    if(n>0x89A10){uint32_t menu=0;std::memcpy(&menu,p+0x89A0C,4);menuTable_.store(menu);}
  }
  if(returningMenu_){
    if(menuTable_.load()==0x8007FEDC){returningMenu_=false;menuReturned_.store(true);}
    else if(++returnMenuFrame_>180){returningMenu_=false;menuReturnFailed_.store(true);}
  }
  const double coreMs=std::chrono::duration<double,std::milli>(afterCore-beforeCore).count();
  const double netMs=std::chrono::duration<double,std::milli>((beforeCore-start)+(end-afterCore)).count();
  recordPerformance(coreMs,netMs,p,n);
}
void CoreHost::recordPerformance(double coreMs,double netMs,const uint8_t* ram,size_t size){
  if(!perfFile_)return;
  const auto now=PerfClock::now();
  perfCore_.add(coreMs);perfNet_.add(netMs);
  if(perfHaveFrame_)perfInterval_.add(std::chrono::duration<double,std::milli>(now-perfLastFrame_).count());
  perfLastFrame_=now;perfHaveFrame_=true;
  if(ram&&size>=0x895AC){
    uint32_t time=0;std::memcpy(&time,ram+0x895A8,sizeof(time));
    if(perfHaveTime_){
      const uint32_t delta=time-perfPreviousTime_;
      if(delta<=8)perfTimeSteps_+=delta;else ++perfTimeDiscontinuities_;
    }
    perfPreviousTime_=time;perfHaveTime_=true;
    uint16_t status=0,command=0;
    std::memcpy(&status,ram+0x47906,2);std::memcpy(&command,ram+0x47908,2);
    if(command==3&&(status==1||status==2))++perfPendingSamples_;
  }
  const double seconds=std::chrono::duration<double>(now-perfWindowStart_).count();
  if(seconds<1)return;
  perfFile_<<std::chrono::duration<double>(now-perfStart_).count()<<','<<seconds<<','
    <<perfCore_.count()<<','<<perfCore_.count()/seconds<<','
    <<perfCore_.mean()<<','<<perfCore_.p95()<<','<<perfCore_.maximum()<<','
    <<perfNet_.mean()<<','<<perfNet_.maximum()<<','<<perfInterval_.p95()<<','<<perfInterval_.maximum()<<','
    <<perfVideoCount_<<','<<perfVideoMs_<<','<<perfPaintCount_.exchange(0)<<','
    <<perfPaintNs_.exchange(0)/1e6<<','<<perfTimeSteps_<<','<<perfTimeDiscontinuities_<<','
    <<perfPendingSamples_<<','<<net_->diagnosticRequests()<<','<<net_->diagnosticCompleted()<<'\n';
  perfFile_.flush();
  perfCore_.clear();perfNet_.clear();perfInterval_.clear();
  perfVideoCount_=perfTimeSteps_=perfTimeDiscontinuities_=perfPendingSamples_=0;
  perfVideoMs_=0;perfWindowStart_=now;
}
bool CoreHost::env(unsigned cmd,void* data){auto& s=*instance;switch(cmd){
 case RETRO_ENVIRONMENT_GET_CAN_DUPE:*static_cast<bool*>(data)=true;return true;
 case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:*static_cast<const char**>(data)=s.systemDir_.c_str();return true;
 case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:*static_cast<const char**>(data)=s.saveDir_.c_str();return true;
 case RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY:*static_cast<const char**>(data)=s.systemDir_.c_str();return true;
 case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:s.format_=*static_cast<retro_pixel_format*>(data);return true;
 case RETRO_ENVIRONMENT_SET_VARIABLES:{auto* v=(retro_variable*)data;for(;v&&v->key;v++){std::string x=v->value?v->value:"";auto p=x.find(';');if(p!=std::string::npos){x=x.substr(p+1);while(!x.empty()&&x.front()==' ')x.erase(x.begin());auto q=x.find('|');if(q!=std::string::npos)x.resize(q);}s.vars_[v->key]=x;}return true;}
 case RETRO_ENVIRONMENT_GET_VARIABLE:{auto* v=(retro_variable*)data;auto it=s.vars_.find(v->key?v->key:"");v->value=it==s.vars_.end()?nullptr:it->second.c_str();return true;}
 case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:*static_cast<bool*>(data)=s.optionsChanged_;s.optionsChanged_=false;return true;
 case RETRO_ENVIRONMENT_SET_GEOMETRY:{const auto geometry=*static_cast<retro_game_geometry*>(data);if(!geometry.base_width||!geometry.base_height)return false;s.av_.geometry=geometry;s.displayAspect_.store(geometry.aspect_ratio>0?geometry.aspect_ratio:static_cast<double>(geometry.base_width)/geometry.base_height);return true;}
 case RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:{const auto info=*static_cast<retro_system_av_info*>(data);if(!info.geometry.base_width||!info.geometry.base_height||info.timing.fps<1||info.timing.sample_rate<1)return false;const bool audioChanged=info.timing.sample_rate!=s.av_.timing.sample_rate;s.av_=info;s.reportedFps_.store(info.timing.fps);s.displayAspect_.store(info.geometry.aspect_ratio>0?info.geometry.aspect_ratio:static_cast<double>(info.geometry.base_width)/info.geometry.base_height);if(audioChanged)s.audio_.open(static_cast<unsigned>(info.timing.sample_rate));return true;}
 case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:static_cast<retro_log_callback*>(data)->log=log;return true;
 case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:return true;
 case RETRO_ENVIRONMENT_GET_LANGUAGE:*static_cast<unsigned*>(data)=0;return true;
 case RETRO_ENVIRONMENT_SHUTDOWN:PostQuitMessage(0);return true;
 case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:return true;
 default:return false;}}
void CoreHost::video(const void* data,unsigned w,unsigned h,size_t pitch){
  auto& s=*instance;
  const auto perfVideoStart=PerfClock::now();
  // Libretro uses (void*)-1 as a sentinel when a hardware-rendered frame is
  // valid. This frontend only supports software frames, so never dereference it.
  const auto address=reinterpret_cast<uintptr_t>(data);
  if(!data||address==~uintptr_t{0}||!w||!h)return;

  const size_t bytesPerPixel=s.format_==RETRO_PIXEL_FORMAT_XRGB8888?4u:2u;
  if(static_cast<size_t>(w)>SIZE_MAX/bytesPerPixel||
     pitch<static_cast<size_t>(w)*bytesPerPixel||
     static_cast<size_t>(h)>SIZE_MAX/static_cast<size_t>(w))return;

  if(!s.videoFrames_.publish(data,w,h,pitch,s.format_))return;
  s.width_=w;s.height_=h;s.pitch_=pitch;
  ++s.perfVideoCount_;
  s.perfVideoMs_+=std::chrono::duration<double,std::milli>(PerfClock::now()-perfVideoStart).count();
}
void CoreHost::sample(int16_t l,int16_t r){int16_t x[2]{l,r};instance->audio_.push(x,1);}size_t CoreHost::samples(const int16_t* p,size_t n){instance->audio_.push(p,n);return n;}
void CoreHost::inputPoll(){instance->pollInput();}
void CoreHost::pollInput(){
  const bool enabled=inputEnabled_.load(std::memory_order_acquire);
  std::array<int,16> keys{},bindings{};for(unsigned i=0;i<16;++i){keys[i]=keys_[i].load();bindings[i]=padBindings_[i].load();}
  const bool controller=controllerEnabled_.load(),second=secondController_.load();
  const auto pair=enabled?tm3input::readPair(controller?controllerIndex_.load():-2,second?controllerIndex2_.load():-2):std::array<tm3input::PadSnapshot,2>{};
  const auto pad=pair[0];
  buttons_=tm3input::sample(enabled,controller,keys,bindings,pad.mask,[](int key){return (GetAsyncKeyState(key)&0x8000)!=0;});
  for(unsigned i=0;i<16;++i){keys[i]=keys2_[i].load();bindings[i]=padBindings2_[i].load();}
  buttons2_=tm3input::sample(enabled&&second,second,keys,bindings,pair[1].mask,[](int key){return (GetAsyncKeyState(key)&0x8000)!=0;});
  const unsigned triangle=(buttons_[RETRO_DEVICE_ID_JOYPAD_X]?1u:0u)|(buttons2_[RETRO_DEVICE_ID_JOYPAD_X]?2u:0u);
  if(tm3Content_&&!returningMenu_&&(triangle&~previousTriangle_)&&net_->connected())net_->noteTrianglePress();
  previousTriangle_=triangle;
  if(returningMenu_){buttons_.fill(0);buttons2_.fill(0);buttons_[RETRO_DEVICE_ID_JOYPAD_X]=returnMenuFrame_%12<3;if(second)buttons2_[RETRO_DEVICE_ID_JOYPAD_X]=returnMenuFrame_%12<3;}
  if(startPulse_.load()>0){buttons_[RETRO_DEVICE_ID_JOYPAD_START]=1;startPulse_.fetch_sub(1);}
}
int16_t CoreHost::inputState(unsigned port,unsigned device,unsigned,unsigned id){if(port>1||device!=RETRO_DEVICE_JOYPAD||(port==1&&!instance->secondController_.load()))return 0;const auto& buttons=port?instance->buttons2_:instance->buttons_;if(id==RETRO_DEVICE_ID_JOYPAD_MASK){uint16_t m=0;for(unsigned i=0;i<16;i++)if(buttons[i])m|=1u<<i;return (int16_t)m;}return id<16?buttons[id]:0;}
void CoreHost::log(int,const char* fmt,...){va_list a;va_start(a,fmt);vfprintf(stderr,fmt,a);va_end(a);}
void CoreHost::paint(HDC dc,const RECT& dst){
  const auto perfPaintStart=PerfClock::now();
  const auto frame=videoFrames_.snapshot();
  if(!frame)return;
  const auto width=frame->width,height=frame->height;
  BITMAPINFO bi{};
  bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
  bi.bmiHeader.biWidth=(LONG)width;
  bi.bmiHeader.biHeight=-(LONG)height;
  bi.bmiHeader.biPlanes=1;
  bi.bmiHeader.biBitCount=32;
  bi.bmiHeader.biCompression=BI_RGB;
  bi.bmiHeader.biSizeImage=static_cast<DWORD>(frame->pixels.size()*sizeof(uint32_t));
  int dw=dst.right-dst.left,dh=dst.bottom-dst.top;const int aspect=aspectMode_.load();double ar=aspect==1?4.0/3.0:displayAspect_.load();int w=dw,h=(int)(w/ar);if(h>dh){h=dh;w=(int)(h*ar);}if(aspect==2){w=dw;h=dh;}int x=(dw-w)/2,y=(dh-h)/2;SetStretchBltMode(dc,smooth_.load()?HALFTONE:COLORONCOLOR);SetBrushOrgEx(dc,0,0,nullptr);StretchDIBits(dc,x,y,w,h,0,0,width,height,frame->pixels.data(),&bi,DIB_RGB_COLORS,SRCCOPY);
  perfPaintCount_.fetch_add(1,std::memory_order_relaxed);
  perfPaintNs_.fetch_add(static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(PerfClock::now()-perfPaintStart).count()),std::memory_order_relaxed);
}

bool CoreHost::screenshot(const std::filesystem::path& file){
  const auto frame=videoFrames_.snapshot();
  if(!frame)return false;
  BITMAPFILEHEADER header{};header.bfType=0x4D42;header.bfOffBits=sizeof(header)+sizeof(BITMAPINFOHEADER);header.bfSize=header.bfOffBits+static_cast<DWORD>(frame->pixels.size()*4);
  BITMAPINFOHEADER info{};info.biSize=sizeof(info);info.biWidth=static_cast<LONG>(frame->width);info.biHeight=-static_cast<LONG>(frame->height);info.biPlanes=1;info.biBitCount=32;info.biCompression=BI_RGB;
  std::ofstream output(file,std::ios::binary);output.write(reinterpret_cast<const char*>(&header),sizeof(header));output.write(reinterpret_cast<const char*>(&info),sizeof(info));output.write(reinterpret_cast<const char*>(frame->pixels.data()),static_cast<std::streamsize>(frame->pixels.size()*4));return output.good();
}
