// Exercise the unchanged shipping NetBridge through externally owned relays.
#define main originalSmokeMain
#include "net_bridge_smoketest.cpp"
#undef main

int main(){
  const char* hp=std::getenv("TM3_QA_HOST_PORT");
  const char* jp=std::getenv("TM3_QA_JOIN_PORT");
  if(!hp||!jp){std::cerr<<"Run tools/verify_relay_transport.py\n";return 1;}
  const auto port=static_cast<uint16_t>(std::strtoul(hp,nullptr,10));
  const auto joinPort=static_cast<uint16_t>(std::strtoul(jp,nullptr,10));
  std::vector<uint8_t> hram(16*1024*1024),cram(16*1024*1024);
  auto& h=mailbox(hram);auto& c=mailbox(cram);
  h.magic=c.magic=kMagic;h.version=c.version=kVersion;
  NetBridge host,client;
  host.poll(hram.data(),hram.size());client.poll(cram.data(),cram.size());
  if(!host.host(port)||!client.join("127.0.0.1",joinPort))return 2;
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
  while(std::chrono::steady_clock::now()<deadline&&(!host.connected()||!client.connected()))
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  if(!host.connected()||!client.connected())return 3;
  requestRole(c);requestRole(h);
  if(!waitForTransfer(h,c)||(h.flags&0xff)!=2||(c.flags&0xff)!=1)return 4;
  std::vector<uint8_t> hv(65536),cv(65536);
  for(size_t i=0;i<hv.size();++i){hv[i]=static_cast<uint8_t>(i*17);cv[i]=static_cast<uint8_t>(i*31);}
  h.status=c.status=0;
  request(hram,0,hv,65536);request(cram,0,cv,65536);
  if(!waitForTransfer(h,c,std::chrono::seconds(10))||!receivedEquals(hram,cv)||!receivedEquals(cram,hv))return 5;
  for(uint32_t tick=0;tick<300;++tick){
    hv.resize(60);cv.resize(60); // Same payload size as the experimental 2+2 batch.
    for(size_t i=0;i<hv.size();++i){hv[i]=static_cast<uint8_t>(tick+i);cv[i]=static_cast<uint8_t>(tick-i);}
    if(tick%53==10)host.dropNextResponsesForTest(2);
    if(tick%71==30)client.dropNextRequestsForTest(1);
    h.status=c.status=0;
    request(hram,0,hv,60,0x8003AA98);request(cram,0,cv,60,0x8003AA98);
    if(!waitForTransfer(h,c,std::chrono::seconds(3))||!receivedEquals(hram,cv)||!receivedEquals(cram,hv))return 6;
  }
  client.requestReturnToMenu();
  bool returnedHost=false,returnedGuest=false;
  const auto cancelDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(std::chrono::steady_clock::now()<cancelDeadline&&(!returnedHost||!returnedGuest)){
    returnedHost=host.consumeReturnToMenu()||returnedHost;
    returnedGuest=client.consumeReturnToMenu()||returnedGuest;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  if(!returnedHost||!returnedGuest||!host.connected()||!client.connected())return 7;
  std::cout<<"PASS: protocol 7 over relay: host role 2 / guest role 1, 64 KiB fragmentation, "
    "300 x 60-byte exchanges with injected packet loss, cancellation keeps transport.\n";
  return 0;
}
