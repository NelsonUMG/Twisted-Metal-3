// Reuse the exact published mailbox fixture and run its existing regressions.
// This creates RAM arrays/socket pairs only. No emulator, game, or live RAM access.
#define main originalSmokeMain
#include "net_bridge_smoketest.cpp"
#undef main

int main(){
  if(const int rc=originalSmokeMain(0,nullptr))return rc;
  std::vector<uint8_t> hram(16*1024*1024),cram(16*1024*1024);
  auto& h=mailbox(hram);auto& c=mailbox(cram);
  h.magic=c.magic=kMagic;h.version=c.version=kVersion;
  NetBridge host,client;
  host.poll(hram.data(),hram.size());client.poll(cram.data(),cram.size());
  const auto port=static_cast<uint16_t>(41000+GetCurrentProcessId()%1000);
  if(!host.host(port))return 50;
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  if(!client.join("127.0.0.1",port))return 51;
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(std::chrono::steady_clock::now()<deadline&&(!(h.flags&kConnected)||!(c.flags&kConnected)))
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  if(!(h.flags&kConnected)||!(c.flags&kConnected))return 52;
  // Transport roles survive local menus. Guest D3298 is separate and remains 0.
  requestRole(c);
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  requestRole(h);
  if(!waitForTransfer(h,c))return 53;
  h.status=c.status=0;
  for(uint32_t cycle=0;cycle<3;++cycle){
    const uint32_t hc=host.diagnosticRequests(),cc=client.diagnosticRequests();
    const uint32_t hs=h.sequence,cs=c.sequence;
    // Simulated independent local menu activity; the bridge must not synchronize it.
    const uint32_t hlocal=100+cycle,clocal=900+cycle;
    std::memcpy(hram.data()+0xD2D40,&hlocal,4);
    std::memcpy(cram.data()+0xD2D40,&clocal,4);
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    if(h.status||c.status||h.sequence!=hs||c.sequence!=cs||
       host.diagnosticRequests()!=hc||client.diagnosticRequests()!=cc||
       readU32(hram,0xD3298)||readU32(cram,0xD3298)||
       readU32(hram,0xD2D40)!=hlocal||readU32(cram,0xD2D40)!=clocal)return 54;

    // First console selects Yes. Reused transport role is not peer confirmation:
    // the real 47EA0 exchange must wait for the other console to issue its request.
    auto& first=cycle%2?hram:cram;auto& second=cycle%2?cram:hram;
    requestRole(mailbox(first));
    const auto reuseDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
    while(std::chrono::steady_clock::now()<reuseDeadline&&mailbox(first).status!=3)
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    if(mailbox(first).status!=3)return 55;
    mailbox(first).status=0;
    const std::vector<uint8_t> previousRole(4,0);
    request(first,0,previousRole,4,0x80047EA0);
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    if(mailbox(first).status!=2||mailbox(second).status!=0)return 56;
    requestRole(mailbox(second));
    const auto secondDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
    while(std::chrono::steady_clock::now()<secondDeadline&&mailbox(second).status!=3)
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    if(mailbox(second).status!=3)return 57;
    mailbox(second).status=0;
    request(second,0,previousRole,4,0x80047EA0);
    if(!waitForTransfer(h,c)||!receivedEquals(hram,previousRole)||!receivedEquals(cram,previousRole))return 58;
    h.status=c.status=0;
    const std::vector<uint8_t> token{0x45,0,0,0};
    request(hram,0,token,4,0x80047EB8);request(cram,0,token,4,0x80047EB8);
    if(!waitForTransfer(h,c)||!receivedEquals(hram,token)||!receivedEquals(cram,token))return 59;
    h.status=c.status=0;
    // New cycle contents at a repeated call site must not replay old data.
    const std::vector<uint8_t> hv{static_cast<uint8_t>(cycle+1),0xAA,0,0};
    const std::vector<uint8_t> cv{static_cast<uint8_t>(cycle+1),0xBB,0,0};
    request(hram,0,hv,4,0x80051EC4);request(cram,0,cv,4,0x80051EC4);
    if(!waitForTransfer(h,c)||!receivedEquals(hram,cv)||!receivedEquals(cram,hv))return 60;
    h.status=c.status=0;
    if(host.diagnosticRequests()!=hc+3||client.diagnosticRequests()!=cc+3||
       h.sequence<=hs||c.sequence<=cs)return 61;
  }
  std::cout<<"PASS: 3 idle-menu/reentry mailbox cycles; local menu fields unchanged; "
              "one-sided Yes waits; fresh payloads. Not a full game reconnection test.\n";
  return 0;
}
