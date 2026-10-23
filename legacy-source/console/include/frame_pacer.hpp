#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

class FramePacer {
public:
  struct Budget {
    uint64_t framesToRun{};
    uint64_t droppedFrames{};
  };

  explicit FramePacer(double framesPerSecond)
    : step_(1.0/(framesPerSecond>1.0?framesPerSecond:60.0)) {}

  Budget advance(double elapsedSeconds,bool waitingForPeer,uint64_t maxCatchUpFrames){
    if(waitingForPeer){
      accumulator_=0.0;
      return {};
    }
    if(!std::isfinite(elapsedSeconds)||elapsedSeconds<0.0)elapsedSeconds=0.0;
    accumulator_+=std::clamp(elapsedSeconds,0.0,0.25);
    const auto dueFrames=static_cast<uint64_t>(
      std::floor((accumulator_+step_*1e-9)/step_));
    if(dueFrames==0)return {};
    if(maxCatchUpFrames==0)maxCatchUpFrames=1;
    const auto framesToRun=std::min(dueFrames,maxCatchUpFrames);
    accumulator_-=static_cast<double>(dueFrames)*step_;
    if(accumulator_<0.0)accumulator_=0.0;
    return {framesToRun,dueFrames-framesToRun};
  }

private:
  double step_{};
  double accumulator_{};
};
