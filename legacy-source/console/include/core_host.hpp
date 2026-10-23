#pragma once
#include "libretro_min.hpp"
#include "audio_waveout.hpp"
#include "net_bridge.hpp"
#include "perf_window.hpp"
#include "video_frames.hpp"
#include <chrono>
#include <fstream>
#include <windows.h>
#include <array>
#include <atomic>
#include <filesystem>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>
#include <memory>

class CoreHost {
public:
  bool load(const std::filesystem::path& core,const std::filesystem::path& game,const std::filesystem::path& base);
  void unload();
  bool loaded() const{return loaded_.load();}
  bool linkedReady() const{return linkedReady_.load();}
  uint32_t mailboxMagic() const{return mailboxMagic_.load();}
  uint32_t menuTable() const{return menuTable_.load();}
  void requestMainMenu(){menuReturned_.store(false);menuReturnFailed_.store(false);menuReturnRequested_.store(true);}
  bool mainMenuReturned() const{return menuReturned_.load();}
  bool mainMenuReturnFailed() const{return menuReturnFailed_.load();}
  void disconnect(){net_=std::make_unique<NetBridge>();}
  void setOption(const std::string& name,const std::string& value){std::scoped_lock lock(optionMutex_);pendingOptions_["beetle_psx_"+name]=value;pendingOptions_["beetle_psx_hw_"+name]=value;}
  void runFrame();
  void paint(HDC dc,const RECT& dst);
  uint64_t videoGeneration() const{return videoFrames_.generation();}
  void setSaveSlot(std::string slot){saveSlot_=std::move(slot);}
  std::filesystem::path saveDirectory() const{return saveSlot_.empty()?base_/L"saves":base_/("saves_"+saveSlot_);}
  void setInputEnabled(bool enabled){inputEnabled_.store(enabled,std::memory_order_release);}
  double fps() const{return reportedFps_.load();}
  uint64_t droppedAudioFrames() const{return audio_.droppedFrames();}
  NetBridge& net(){return *net_;}
  void setAspect(int value){aspectMode_.store(value);}
  void setSmooth(bool value){smooth_.store(value);}
  void setVolume(int value){audio_.setVolume(value);}
  void setMuted(bool value){audio_.setMuted(value);}
  void setController(bool value){controllerEnabled_.store(value);}
  void setKey(unsigned id,int value,unsigned port=0){if(id<16)(port?keys2_:keys_)[id].store(value);}
  void setPad(unsigned id,int value,unsigned port=0){if(id<16)(port?padBindings2_:padBindings_)[id].store(value);}
  void setSecondController(bool enabled,int index){if(secondController_.exchange(enabled)!=enabled)secondPortChanged_.store(true);controllerIndex2_.store(index);}
  bool secondController() const{return secondController_.load();}
  void setControllerIndex(int value){controllerIndex_.store(value);}
  void setGraphics(int resolution,bool pgxp,bool widescreen);
  int resolution() const{return resolution_.load();}
  int keyBinding(unsigned id,unsigned port=0) const{return id<16?(port?keys2_:keys_)[id].load():0;}
  int padBinding(unsigned id,unsigned port=0) const{return id<16?(port?padBindings2_:padBindings_)[id].load():0;}
  double aspectRatio() const{return displayAspect_.load();}
  std::array<unsigned,2> frameSize(){const auto frame=videoFrames_.snapshot();return frame?std::array<unsigned,2>{frame->width,frame->height}:std::array<unsigned,2>{0,0};}
  void setAudioDevice(int value){audio_.setDevice(value);}
  void setAudioLatency(int value){audio_.setLatency(value);}
  void pressStart(){startPulse_.store(3);}
  void requestReset(){resetRequested_.store(true);}
  bool screenshot(const std::filesystem::path& file);
  static CoreHost* instance;
private:
  std::atomic<bool> linkedReady_{false};
  std::atomic<uint32_t> mailboxMagic_{0},menuTable_{0};
  std::atomic<bool> menuReturnRequested_{false},menuReturned_{false},menuReturnFailed_{false};
  bool returningMenu_=false;
  unsigned previousTriangle_=0;
  unsigned returnMenuFrame_=0;
  HMODULE dll_{}; retro_system_av_info av_{}; retro_pixel_format format_=RETRO_PIXEL_FORMAT_XRGB8888;
  std::filesystem::path base_; std::string systemDir_,saveDir_,contentDir_,saveSlot_;
  std::unordered_map<std::string,std::string> vars_;
  std::mutex optionMutex_;
  std::unordered_map<std::string,std::string> pendingOptions_;
  bool optionsChanged_=false;
  std::atomic<int> resolution_{1};
  std::atomic<double> displayAspect_{4.0/3.0};
  std::atomic<double> reportedFps_{60.0};
  VideoFrames videoFrames_;
  unsigned width_=0,height_=0; size_t pitch_=0;
  AudioWaveOut audio_; std::unique_ptr<NetBridge> net_=std::make_unique<NetBridge>();
  std::atomic<bool> loaded_{false};
  bool initialized_=false,tm3Content_=false;
  std::atomic<bool> inputEnabled_{true};
  std::atomic<int> aspectMode_{0},startPulse_{0};
  std::atomic<bool> smooth_{false},controllerEnabled_{true},resetRequested_{false};
  std::array<std::atomic<int>,16> keys_{};
  std::array<std::atomic<int>,16> padBindings_{};
  std::atomic<int> controllerIndex_{-1};
  std::array<int16_t,16> buttons_{};
  std::array<std::atomic<int>,16> keys2_{},padBindings2_{};
  std::atomic<int> controllerIndex2_{-1};
  std::atomic<bool> secondController_{false},secondPortChanged_{false};
  std::array<int16_t,16> buttons2_{};
  using PerfClock=std::chrono::steady_clock;
  std::ofstream perfFile_;
  PerfClock::time_point perfStart_,perfWindowStart_,perfLastFrame_;
  PerfWindow perfCore_,perfNet_,perfInterval_;
  std::atomic<uint64_t> perfPaintCount_{0},perfPaintNs_{0};
  uint64_t perfVideoCount_{0},perfTimeSteps_{0},perfTimeDiscontinuities_{0},perfPendingSamples_{0};
  double perfVideoMs_{0};
  uint32_t perfPreviousTime_{0};
  bool perfHaveTime_{false},perfHaveFrame_{false};
  void recordPerformance(double coreMs,double netMs,const uint8_t* ram,size_t size);
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
  FN(retro_reset,void)
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
