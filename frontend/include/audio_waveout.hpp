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
  void push(const int16_t* interleavedStereo, size_t frames);
  uint64_t droppedFrames() const{return droppedFrames_.load(std::memory_order_relaxed);}
private:
  static constexpr size_t kBlocks=8, kFramesPerBlock=2048;
  HWAVEOUT out_{};
  std::array<WAVEHDR,kBlocks> headers_{};
  std::array<std::vector<int16_t>,kBlocks> blocks_{};
  size_t current_=0, fillFrames_=0;
  std::mutex mutex_;
  std::atomic<uint64_t> droppedFrames_{0};
  bool currentBlockWritable();
  void submitCurrent();
};
