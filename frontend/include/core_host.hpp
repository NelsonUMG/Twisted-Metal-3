#pragma once
#include "libretro_min.hpp"
#include "audio_waveout.hpp"
#include "net_bridge.hpp"
#include <windows.h>
#include <array>
#include <atomic>
#include <filesystem>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

class CoreHost {
public:
  bool load(const std::filesystem::path& core,const std::filesystem::path& game,const std::filesystem::path& base);
  void unload();
  void runFrame();
  void paint(HDC dc,const RECT& dst);
  void setSaveSlot(std::string slot){saveSlot_=std::move(slot);}
  void setInputEnabled(bool enabled){inputEnabled_.store(enabled,std::memory_order_release);}
  double fps() const{return av_.timing.fps>1?av_.timing.fps:60.0;}
  uint64_t droppedAudioFrames() const{return audio_.droppedFrames();}
  NetBridge& net(){return net_;}
  static CoreHost* instance;
private:
  HMODULE dll_{}; retro_system_av_info av_{}; retro_pixel_format format_=RETRO_PIXEL_FORMAT_XRGB8888;
  std::filesystem::path base_; std::string systemDir_,saveDir_,contentDir_,saveSlot_;
  std::unordered_map<std::string,std::string> vars_;
  std::mutex frameMutex_;
  std::vector<uint32_t> frame32_; unsigned width_=0,height_=0; size_t pitch_=0;
  AudioWaveOut audio_; NetBridge net_;
  std::atomic<bool> inputEnabled_{true};
  std::array<int16_t,16> buttons_{};
#define FN(name,ret,...) using name##_t=ret(*)(__VA_ARGS__); name##_t name{};
  FN(retro_api_version,unsigned)
  FN(retro_init,void)
  FN(retro_deinit,void)
  FN(retro_get_system_info,void,retro_system_info*)
  FN(retro_get_system_av_info,void,retro_system_av_info*)
  FN(retro_set_environment,void,retro_environment_t)
  FN(retro_set_video_refresh,void,retro_video_refresh_t)
  FN(retro_set_audio_sample,void,retro_audio_sample_t)
  FN(retro_set_audio_sample_batch,void,retro_audio_sample_batch_t)
  FN(retro_set_input_poll,void,retro_input_poll_t)
  FN(retro_set_input_state,void,retro_input_state_t)
  FN(retro_set_controller_port_device,void,unsigned,unsigned)
  FN(retro_run,void)
  FN(retro_load_game,bool,const retro_game_info*)
  FN(retro_unload_game,void)
  FN(retro_get_memory_data,void*,unsigned)
  FN(retro_get_memory_size,size_t,unsigned)
#undef FN
  template<class T> bool sym(T& out,const char* n){out=reinterpret_cast<T>(GetProcAddress(dll_,n));return out!=nullptr;}
  static bool env(unsigned,void*); static void video(const void*,unsigned,unsigned,size_t);
  static void sample(int16_t,int16_t); static size_t samples(const int16_t*,size_t);
  static void inputPoll(); static int16_t inputState(unsigned,unsigned,unsigned,unsigned);
  static void log(int,const char*,...);
  void pollInput();
};
