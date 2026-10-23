#include "audio_waveout.hpp"
#include <algorithm>
#include <cstring>

AudioWaveOut::~AudioWaveOut(){
  if(out_){ waveOutReset(out_); for(auto& h:headers_) if(h.dwFlags&WHDR_PREPARED) waveOutUnprepareHeader(out_,&h,sizeof(h)); waveOutClose(out_); }
}
bool AudioWaveOut::open(unsigned rate){
  WAVEFORMATEX f{}; f.wFormatTag=WAVE_FORMAT_PCM; f.nChannels=2; f.nSamplesPerSec=rate;
  f.wBitsPerSample=16; f.nBlockAlign=4; f.nAvgBytesPerSec=rate*4;
  if(waveOutOpen(&out_,WAVE_MAPPER,&f,0,0,CALLBACK_NULL)!=MMSYSERR_NOERROR) return false;
  for(size_t i=0;i<kBlocks;i++) blocks_[i].resize(kFramesPerBlock*2);
  return true;
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
}
void AudioWaveOut::push(const int16_t* src,size_t frames){
  std::scoped_lock lock(mutex_);
  if(!out_){droppedFrames_.fetch_add(frames,std::memory_order_relaxed);return;}
  while(frames){
    // El callback de audio se ejecuta dentro de retro_run(). Nunca debe
    // esperar a WaveOut: con dos cores, esa espera alimentaba la deuda del
    // reloj y cada minuto intentaba recuperar mas cuadros que el anterior.
    // Si los ocho bloques siguen ocupados, descarta exclusivamente el audio
    // atrasado; la emulacion y NetBridge continúan en tiempo real.
    if(fillFrames_==0&&!currentBlockWritable()){
      droppedFrames_.fetch_add(frames,std::memory_order_relaxed);
      return;
    }
    size_t n=std::min(frames,kFramesPerBlock-fillFrames_);
    std::memcpy(blocks_[current_].data()+fillFrames_*2,src,n*4);
    fillFrames_+=n; src+=n*2; frames-=n;
    if(fillFrames_==kFramesPerBlock) submitCurrent();
  }
}
