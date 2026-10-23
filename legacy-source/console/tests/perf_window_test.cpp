#include "perf_window.hpp"
#include <limits>
#include <stdexcept>
#include <iostream>
void require(bool value){if(!value)throw std::runtime_error("perf statistics test failed");}
int main(){
  PerfWindow window;
  require(window.count()==0&&window.p95()==0&&window.mean()==0);
  for(int i=1;i<=100;++i)window.add(i);
  require(window.count()==100&&window.p95()==95&&window.mean()==50.5&&window.maximum()==100);
  window.add(-1);window.add(std::numeric_limits<double>::infinity());
  require(window.count()==100);
  window.clear();window.add(33.333);
  require(window.p95()==33.333&&window.maximum()==33.333);
  for(int i=0;i<5000;++i)window.add(1);
  require(window.count()==4096);
  std::cout<<"Bounded sample count, mean, p95, max, invalid values: PASS\n";
}
