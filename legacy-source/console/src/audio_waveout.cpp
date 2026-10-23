#include "audio_waveout.hpp"
#include "audio_gain.hpp"
#include <algorithm>
#include <cstring>

AudioWaveOut::~AudioWaveOut(){closeDevice();}
void AudioWaveOut::closeDevice(){
  if(out_){ waveOutReset(out_); for(auto& h:headers_) if(h.dwFlags&WHDR_PREPARED) waveOutUnprepareHeader(out_,&h,sizeof(h)); waveOutClose(out_);out_=nullptr; }
  headers_={};current_=fillFrames_=0;buffering_.store(true);
}
bool AudioWaveOut::open(unsigned rate){
  std::scoped_lock lock(mutex_);return openDevice(rate);
}
bool AudioWaveOut::openDevice(unsigned rate){
  closeDevice();sampleRate_=rate;activeLatency_=requestedLatency_.load();framesPerBlock_=std::max<size_t>(128,rate*activeLatency_/1000/kBlocks);
  WAVEFORMATEX f{}; f.wFormatTag=WAVE_FORMAT_PCM; f.nChannels=2; f.nSamplesPerSec=rate;
  f.wBitsPerSample=16; f.nBlockAlign=4; f.nAvgBytesPerSec=rate*4;
  activeDevice_=requestedDevice_.load();
  if(waveOutOpen(&out_,activeDevice_<0?WAVE_MAPPER:static_cast<UINT>(activeDevice_),&f,0,0,CALLBACK_NULL)!=MMSYSERR_NOERROR){
    activeDevice_=-1;requestedDevice_.store(-1);if(waveOutOpen(&out_,WAVE_MAPPER,&f,0,0,CALLBACK_NULL)!=MMSYSERR_NOERROR)return false;
  }
  for(size_t i=0;i<kBlocks;i++) blocks_[i].resize(framesPerBlock_*2);
  // Capacity is not a reserve. Hold playback until half the queue is ready.
  // This is an original WaveOut implementation; no DuckStation code is copied.
  if(waveOutPause(out_)!=MMSYSERR_NOERROR){closeDevice();return false;}
  return true;
}
size_t AudioWaveOut::queuedBlocks() const{
  size_t queued=0;
  for(const auto& header:headers_)
    if((header.dwFlags&WHDR_PREPARED)&&!(header.dwFlags&WHDR_DONE))++queued;
  return queued;
}
bool AudioWaveOut::currentBlockWritable(){
  auto& h=headers_[current_];
  if(!(h.dwFlags&WHDR_PREPARED))return true;
  if(!(h.dwFlags&WHDR_DONE))return false;
  if(waveOutUnprepareHeader(out_,&h,sizeof(h))!=MMSYSERR_NOERROR)return false;
  h={};
  return true;
}
void AudioWaveOut::submitCurrent(){
  if(!out_||fillFrames_==0) return;
  auto& h=headers_[current_];
  h={}; h.lpData=reinterpret_cast<LPSTR>(blocks_[current_].data()); h.dwBufferLength=static_cast<DWORD>(fillFrames_*4);
  if(waveOutPrepareHeader(out_,&h,sizeof(h))!=MMSYSERR_NOERROR||
     waveOutWrite(out_,&h,sizeof(h))!=MMSYSERR_NOERROR){
    droppedFrames_.fetch_add(fillFrames_,std::memory_order_relaxed);
    if(h.dwFlags&WHDR_PREPARED)waveOutUnprepareHeader(out_,&h,sizeof(h));
    h={};
  }
  current_=(current_+1)%kBlocks; fillFrames_=0;
  if(buffering_.load()&&queuedBlocks()>=kStartBlocks){
    if(waveOutRestart(out_)==MMSYSERR_NOERROR)buffering_.store(false);
    else {closeDevice();}
  }
}
void AudioWaveOut::push(const int16_t* src,size_t frames){
  std::scoped_lock lock(mutex_);
  if(requestedDevice_.load()!=activeDevice_||requestedLatency_.load()!=activeLatency_)openDevice(sampleRate_);
  if(!out_){droppedFrames_.fetch_add(frames,std::memory_order_relaxed);return;}
  if(!buffering_.load()&&queuedBlocks()==0){
    underruns_.fetch_add(1,std::memory_order_relaxed);
    // A drained queue must rebuild its reserve, not repeatedly restart on
    // every tiny chunk. Never sleep or wait inside the emulation callback.
    if(waveOutPause(out_)!=MMSYSERR_NOERROR){closeDevice();droppedFrames_.fetch_add(frames);return;}
    buffering_.store(true);
  }
  while(frames){
    if(!out_){droppedFrames_.fetch_add(frames,std::memory_order_relaxed);return;}
    // El callback de audio se ejecuta dentro de retro_run(). Nunca debe
    // esperar a WaveOut: con dos cores, esa espera alimentaba la deuda del
    // reloj y cada minuto intentaba recuperar mas cuadros que el anterior.
    // Si los ocho bloques siguen ocupados, descarta exclusivamente el audio
    // atrasado; la emulacion y NetBridge continúan en tiempo real.
    if(fillFrames_==0&&!currentBlockWritable()){
      droppedFrames_.fetch_add(frames,std::memory_order_relaxed);
      return;
    }
    size_t n=std::min(frames,framesPerBlock_-fillFrames_);
    auto* destination=blocks_[current_].data()+fillFrames_*2;
    tm3audio::scale(destination,src,n*2,volume_.load(),muted_.load());
    fillFrames_+=n; src+=n*2; frames-=n;
    if(fillFrames_==framesPerBlock_) submitCurrent();
  }
}
