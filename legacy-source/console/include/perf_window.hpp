#pragma once
#include <algorithm>
#include <cmath>
#include <vector>

// A bounded host-time sample window. No emulation scheduling or guest writes.
class PerfWindow {
public:
  void add(double ms){if(std::isfinite(ms)&&ms>=0&&values_.size()<4096)values_.push_back(ms);}
  double mean() const {double total=0;for(auto v:values_)total+=v;return values_.empty()?0:total/values_.size();}
  double maximum() const {return values_.empty()?0:*std::max_element(values_.begin(),values_.end());}
  double p95() const {
    if(values_.empty())return 0;
    auto sorted=values_;std::sort(sorted.begin(),sorted.end());
    return sorted[static_cast<size_t>(std::ceil(sorted.size()*0.95))-1];
  }
  size_t count() const{return values_.size();}
  void clear(){values_.clear();}
private:
  std::vector<double> values_;
};
