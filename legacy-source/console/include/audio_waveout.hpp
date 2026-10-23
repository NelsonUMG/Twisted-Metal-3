#pragma once
#include <windows.h>
#include <mmsystem.h>
#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <vector>

class AudioWaveOut {
public:
  ~AudioWaveOut();
  bool open(unsigned sampleRate);
  void close(){std::scoped_lock lock(mutex_);closeDevice();}
  void setLatency(int milliseconds){requestedLatency_.store(milliseconds==20?20:milliseconds==40?40:80);}
  void push(const int16_t* interleavedStereo, size_t frames);
  uint64_t droppedFrames() const{return droppedFrames_.load(std::memory_order_relaxed);}
  uint64_t underruns() const{return underruns_.load(std::memory_order_relaxed);}
  bool buffering() const{return buffering_.load(std::memory_order_relaxed);}
  void setVolume(int value){volume_.store(value);}
  void setMuted(bool value){muted_.store(value);}
  void setDevice(int value){requestedDevice_.store(value);}
private:
  static constexpr size_t kBlocks=8, kStartBlocks=4;
  HWAVEOUT out_{};
  std::array<WAVEHDR,kBlocks> headers_{};
  std::array<std::vector<int16_t>,kBlocks> blocks_{};
  size_t current_=0, fillFrames_=0;
  std::mutex mutex_;
  std::atomic<uint64_t> droppedFrames_{0};
  std::atomic<uint64_t> underruns_{0};
  std::atomic<bool> buffering_{true};
  std::atomic<int> volume_{100};
  std::atomic<bool> muted_{false};
  std::atomic<int> requestedDevice_{-1};
  int activeDevice_=-1;
  unsigned sampleRate_=44100;
  std::atomic<int> requestedLatency_{80};
  int activeLatency_=80;
  size_t framesPerBlock_=512;
  void closeDevice();
  bool openDevice(unsigned sampleRate);
  bool currentBlockWritable();
  void submitCurrent();
  size_t queuedBlocks() const;
};
