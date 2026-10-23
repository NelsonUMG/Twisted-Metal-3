#include "net_bridge.hpp"
#include <windows.h>
#include <array>
#include <chrono>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <numeric>
#include <thread>
#include <vector>

#pragma pack(push,1)
struct TestSegment {
  uint32_t address,size;
};
struct TestMailbox {
  uint32_t magic;
  uint16_t version,status;
  uint16_t command,flags;
  uint32_t sequence,sendSize,recvCapacity,recvSize,callSite;
  uint32_t sendAddress,recvAddress;
  uint32_t sendSegmentCount,recvSegmentCount;
  TestSegment sendSegments[4],recvSegments[4];
};
#pragma pack(pop)

static_assert(sizeof(TestMailbox)==112);
static constexpr size_t kMailboxOffset=0x47900;
static constexpr size_t kDirectSendOffset=0x90000,kDirectRecvOffset=0xA0000;
static constexpr uint32_t kMagic=0x4F334D54;
static constexpr uint16_t kVersion=5,kConnected=0x0100,kExpanded=0x0200;
static constexpr uint16_t kTransfer=2,kBatchTransfer=3;
static constexpr size_t kRngCounterOffset=0xF00010;
static constexpr size_t kRngMagicOffset=0xF00014;
static constexpr size_t kRngVersionOffset=0xF00018;
static constexpr size_t kRngCodecaveOffset=0xF10100;
static constexpr uint32_t kRngDiagMagic=0x31474E52;
static constexpr std::array<uint32_t,15> kExpectedRngCodecaveWords{
  0x8F820708u,0x3C0880F0u,0x8D090010u,0x00000000u,0x312A0FFFu,
  0x000A5100u,0x250B0020u,0x016A5821u,0xAD7F0000u,0xAD620004u,
  0x25290001u,0xAD090010u,0x3C0341C6u,0x0800E83Eu,0x00000000u,
};

static uint32_t readU32(const std::vector<uint8_t>& ram,size_t offset){
  uint32_t value=0;
  std::memcpy(&value,ram.data()+offset,sizeof(value));
  return value;
}

static TestMailbox& mailbox(std::vector<uint8_t>& ram){
  return *reinterpret_cast<TestMailbox*>(ram.data()+kMailboxOffset);
}

static uint32_t kseg0(size_t offset){
  return 0x80000000u|static_cast<uint32_t>(offset);
}

static void publish(TestMailbox& box){
  MemoryBarrier();box.status=1;MemoryBarrier();
}

static void request(std::vector<uint8_t>& ram,uint32_t sequence,
                    const std::vector<uint8_t>& payload,uint32_t expected,
                    uint32_t callSite=0x80047EA0,
                    size_t sendOffset=kDirectSendOffset,size_t recvOffset=kDirectRecvOffset){
  auto& box=mailbox(ram);
  box.magic=kMagic;box.version=kVersion;box.status=0;box.command=kTransfer;box.sequence=sequence;
  box.sendSize=static_cast<uint32_t>(payload.size());box.recvCapacity=expected;box.recvSize=0;
  box.callSite=callSite;box.sendAddress=kseg0(sendOffset);box.recvAddress=kseg0(recvOffset);
  box.sendSegmentCount=0;box.recvSegmentCount=0;
  if(!payload.empty())std::memcpy(ram.data()+sendOffset,payload.data(),payload.size());
  publish(box);
}

static void requestText(std::vector<uint8_t>& ram,uint32_t sequence,const char* payload,
                        uint32_t expected,uint32_t callSite=0x80047EA0){
  const auto* begin=reinterpret_cast<const uint8_t*>(payload);
  request(ram,sequence,std::vector<uint8_t>(begin,begin+std::strlen(payload)),expected,callSite);
}

static std::vector<uint8_t> concatenate(const std::array<std::vector<uint8_t>,4>& parts){
  size_t total=0;
  for(const auto& part:parts)total+=part.size();
  std::vector<uint8_t> output;
  output.reserve(total);
  for(const auto& part:parts)output.insert(output.end(),part.begin(),part.end());
  return output;
}

static void requestBatch(std::vector<uint8_t>& ram,
                         const std::array<std::vector<uint8_t>,4>& sendParts,
                         const std::array<uint32_t,4>& receiveSizes,
                         uint32_t callSite=0x8003AA98){
  static constexpr std::array<size_t,4> sendOffsets{0x120000,0x121000,0x122000,0x123000};
  static constexpr std::array<size_t,4> recvOffsets{0x130000,0x131000,0x132000,0x133000};
  auto& box=mailbox(ram);
  box.magic=kMagic;box.version=kVersion;box.status=0;box.command=kBatchTransfer;box.sequence=0;
  box.sendSize=0;box.recvCapacity=0;box.recvSize=0;box.callSite=callSite;
  box.sendAddress=0;box.recvAddress=0;box.sendSegmentCount=4;box.recvSegmentCount=4;
  for(size_t index=0;index<4;++index){
    box.sendSegments[index]={kseg0(sendOffsets[index]),static_cast<uint32_t>(sendParts[index].size())};
    box.recvSegments[index]={kseg0(recvOffsets[index]),receiveSizes[index]};
    box.sendSize+=box.sendSegments[index].size;
    box.recvCapacity+=box.recvSegments[index].size;
    if(!sendParts[index].empty())
      std::memcpy(ram.data()+sendOffsets[index],sendParts[index].data(),sendParts[index].size());
  }
  publish(box);
}

static std::vector<uint8_t> readBatch(const std::vector<uint8_t>& ram,
                                      const std::array<uint32_t,4>& sizes){
  static constexpr std::array<size_t,4> offsets{0x130000,0x131000,0x132000,0x133000};
  std::vector<uint8_t> output;
  for(size_t index=0;index<4;++index)
    output.insert(output.end(),ram.begin()+offsets[index],ram.begin()+offsets[index]+sizes[index]);
  return output;
}

static void requestRole(TestMailbox& box){
  box.magic=kMagic;box.version=kVersion;box.status=0;box.command=1;
  box.sendSize=0;box.recvCapacity=0;box.recvSize=0;
  publish(box);
}

static bool waitForTransfer(TestMailbox& first,TestMailbox& second,
                            std::chrono::seconds timeout=std::chrono::seconds(6)){
  const auto deadline=std::chrono::steady_clock::now()+timeout;
  while(std::chrono::steady_clock::now()<deadline){
    if(first.status==3&&second.status==3)return true;
    if(first.status==4||second.status==4)return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  return false;
}

static bool receivedEquals(const std::vector<uint8_t>& ram,const std::vector<uint8_t>& expected,
                           size_t offset=kDirectRecvOffset){
  return std::memcmp(ram.data()+offset,expected.data(),expected.size())==0;
}

int main(int argc,char** argv){
  uint32_t stressRounds=0;
  if(argc==2&&std::strncmp(argv[1],"--stress=",9)==0)
    stressRounds=static_cast<uint32_t>(std::strtoul(argv[1]+9,nullptr,10));
  // El puente acepta la RAM que el core exponga. Usar 16 MiB aqui prueba que
  // las direcciones ampliadas no se truncan a los 2 MiB de una PS1 original.
  std::vector<uint8_t> hostRam(16*1024*1024),clientRam(16*1024*1024);
  mailbox(hostRam).magic=kMagic;mailbox(hostRam).version=kVersion;
  mailbox(clientRam).magic=kMagic;mailbox(clientRam).version=kVersion;
  NetBridge host,client;
  host.poll(hostRam.data(),hostRam.size());client.poll(clientRam.data(),clientRam.size());
  if(readU32(hostRam,kRngCounterOffset)!=0||
     readU32(hostRam,kRngMagicOffset)!=kRngDiagMagic||
     readU32(hostRam,kRngVersionOffset)!=1||
     std::memcmp(hostRam.data()+kRngCodecaveOffset,kExpectedRngCodecaveWords.data(),
                 sizeof(kExpectedRngCodecaveWords))!=0||
     host.status().find("rnglog=ON rngcalls=0")==std::string::npos){
    std::cerr<<"instrumentacion RNGCaller no se instalo en RAM de 16 MiB\n";return 28;
  }
  const auto port=static_cast<uint16_t>(38000+(GetCurrentProcessId()%1000));
  if(!host.host(port)){std::cerr<<"host() fallo\n";return 1;}
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  if(!client.join("127.0.0.1",port)){std::cerr<<"join() fallo\n";return 2;}
  const auto handshakeDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(std::chrono::steady_clock::now()<handshakeDeadline){
    if(host.status().starts_with("conectado")&&client.status().starts_with("conectado"))break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  if(!host.status().starts_with("conectado")||!client.status().starts_with("conectado")){
    std::cerr<<"handshake fallo: host="<<host.status()<<" client="<<client.status()<<"\n";return 3;
  }
  const auto connectionDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
  while(std::chrono::steady_clock::now()<connectionDeadline){
    if((mailbox(hostRam).flags&(kConnected|kExpanded))==(kConnected|kExpanded)&&
       (mailbox(clientRam).flags&(kConnected|kExpanded))==(kConnected|kExpanded))break;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  if((mailbox(hostRam).flags&(kConnected|kExpanded))!=(kConnected|kExpanded)||
     (mailbox(clientRam).flags&(kConnected|kExpanded))!=(kConnected|kExpanded)){
    std::cerr<<"estado conectado incorrecto\n";return 4;
  }

  // La cliente entra primero y queda en espera; quien entra segundo recibe
  // autoridad, independientemente de quien aloja la sesion TCP.
  requestRole(mailbox(clientRam));
  std::this_thread::sleep_for(std::chrono::milliseconds(250));
  if(mailbox(clientRam).status!=2||mailbox(hostRam).status!=0||
     (mailbox(clientRam).flags&(kConnected|kExpanded))!=(kConnected|kExpanded)){
    std::cerr<<"espera inicial no quedo sondeable\n";return 15;
  }
  requestRole(mailbox(hostRam));
  if(!waitForTransfer(mailbox(hostRam),mailbox(clientRam))||
     (mailbox(hostRam).flags&0xff)!=2||(mailbox(clientRam).flags&0xff)!=1){
    std::cerr<<"asignacion dinamica cliente-primero fallo\n";return 5;
  }
  mailbox(hostRam).status=0;mailbox(clientRam).status=0;

  requestRole(mailbox(clientRam));
  const auto roleReuseDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
  while(std::chrono::steady_clock::now()<roleReuseDeadline&&
        mailbox(clientRam).status!=3&&mailbox(clientRam).status!=4)
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  if(mailbox(clientRam).status!=3||(mailbox(clientRam).flags&0xff)!=1||
     mailbox(hostRam).status!=0||(mailbox(hostRam).flags&0xff)!=2){
    std::cerr<<"reentrada SIO cambio o bloqueo el rol\n";return 16;
  }
  mailbox(clientRam).status=0;

  // Perdida del REQUEST y de la respuesta: la retransmision debe completar.
  host.dropNextDatagramsForTest(2);
  requestText(clientRam,1,"SOFIA",5);
  std::this_thread::sleep_for(std::chrono::milliseconds(250));
  requestText(hostRam,1,"OSCAR",5);
  auto& hostBox=mailbox(hostRam);auto& clientBox=mailbox(clientRam);
  if(!waitForTransfer(hostBox,clientBox)||hostBox.sequence!=1||clientBox.sequence!=1||
     hostBox.recvSize!=5||clientBox.recvSize!=5||
     std::memcmp(hostRam.data()+kDirectRecvOffset,"SOFIA",5)!=0||
     std::memcmp(clientRam.data()+kDirectRecvOffset,"OSCAR",5)!=0){
    std::cerr<<"transferencia con perdida fallo\n";return 6;
  }

  hostBox.status=0;clientBox.status=0;
  requestText(clientRam,3,"",4);
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  requestText(hostRam,3,"CFG2",0);
  if(!waitForTransfer(hostBox,clientBox)||hostBox.recvSize!=0||clientBox.recvSize!=4||
     std::memcmp(clientRam.data()+kDirectRecvOffset,"CFG2",4)!=0||
     hostBox.sequence!=2||clientBox.sequence!=2){
    std::cerr<<"transferencia asimetrica fallo\n";return 7;
  }

  hostBox.status=0;clientBox.status=0;
  host.setNextSequenceForTest(517);client.setNextSequenceForTest(518);
  requestText(clientRam,0,"SOFIA-OFFSET",12);
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  requestText(hostRam,0,"OSCAR-OFFSET",12);
  if(!waitForTransfer(hostBox,clientBox)||hostBox.sequence!=518||clientBox.sequence!=519||
     std::memcmp(hostRam.data()+kDirectRecvOffset,"SOFIA-OFFSET",12)!=0||
     std::memcmp(clientRam.data()+kDirectRecvOffset,"OSCAR-OFFSET",12)!=0){
    std::cerr<<"secuencias desalineadas fallo\n";return 9;
  }

  // Los cuatro buffers que TM3 intercambia cada tick viajan como un solo
  // snapshot logico de 36 bytes, conservando sus destinos originales.
  const std::array<std::vector<uint8_t>,4> hostParts{{
    {'H','D','R','H'},std::vector<uint8_t>(24,0xA5),{'H','S','1','!'}, {'H','S','2','!'}}};
  const std::array<std::vector<uint8_t>,4> clientParts{{
    {'H','D','R','C'},std::vector<uint8_t>(24,0x5A),{'C','S','1','!'}, {'C','S','2','!'}}};
  const std::array<uint32_t,4> batchSizes{4,24,4,4};
  hostBox.status=0;clientBox.status=0;
  requestBatch(clientRam,clientParts,batchSizes);
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  requestBatch(hostRam,hostParts,batchSizes);
  if(!waitForTransfer(hostBox,clientBox)||hostBox.recvSize!=36||clientBox.recvSize!=36||
     readBatch(hostRam,batchSizes)!=concatenate(clientParts)||
     readBatch(clientRam,batchSizes)!=concatenate(hostParts)){
    std::cerr<<"scatter/gather batch de gameplay fallo\n";return 19;
  }

  // Si se pierden tanto el REQUEST como varias respuestas de un tick, el par
  // Two local humans per console require 48 vehicle bytes + 12 framing bytes.
  {
    auto twoHost=hostParts,twoClient=clientParts;
    twoHost[1]=std::vector<uint8_t>(48,0xA5);twoClient[1]=std::vector<uint8_t>(48,0x5A);
    twoHost[1][24]=0x12;twoClient[1][24]=0x34;
    const std::array<uint32_t,4> twoSizes{4,48,4,4};
    hostBox.status=0;clientBox.status=0;
    requestBatch(clientRam,twoClient,twoSizes);requestBatch(hostRam,twoHost,twoSizes);
    if(!waitForTransfer(hostBox,clientBox)||hostBox.recvSize!=60||clientBox.recvSize!=60||
       readBatch(hostRam,twoSizes)!=concatenate(twoClient)||readBatch(clientRam,twoSizes)!=concatenate(twoHost)){
      std::cerr<<"2+2 human gameplay batch failed\n";return 64;
    }
  }
  // Si se pierden tanto el REQUEST como varias respuestas de un tick, el par
  // que ya avanzo puede publicar el tick siguiente. Ese REQUEST futuro tiene
  // exactamente callSite y tamanos iguales, pero no debe completar el tick
  // anterior. El ordinal por callSite conserva el FIFO logico del SIO1.
  constexpr uint32_t kLossCallSite=0x8003AA99;
  hostBox.status=0;clientBox.status=0;
  host.dropNextRequestsForTest(1);
  host.dropNextResponsesForTest(8);
  requestText(clientRam,0,"PEER-N00",8,kLossCallSite);
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  requestText(hostRam,0,"HOST-N00",8,kLossCallSite);
  const auto hostAdvancedDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
  while(std::chrono::steady_clock::now()<hostAdvancedDeadline&&hostBox.status!=3)
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  if(hostBox.status!=3||clientBox.status!=2){
    std::cerr<<"no se reprodujo la espera unilateral con perdida\n";return 23;
  }
  hostBox.status=0;
  requestText(hostRam,0,"HOST-N01",8,kLossCallSite);
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  if(clientBox.status!=2||hostBox.status!=2){
    std::cerr<<"REQUEST futuro completo el ordinal anterior\n";return 24;
  }
  const auto oldTickDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
  while(std::chrono::steady_clock::now()<oldTickDeadline&&clientBox.status!=3&&clientBox.status!=4)
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  if(clientBox.status!=3||!receivedEquals(clientRam,
       std::vector<uint8_t>{'H','O','S','T','-','N','0','0'})){
    std::cerr<<"replay no recupero el ordinal anterior\n";return 25;
  }
  clientBox.status=0;
  requestText(clientRam,0,"PEER-N01",8,kLossCallSite);
  if(!waitForTransfer(hostBox,clientBox)||
     !receivedEquals(hostRam,std::vector<uint8_t>{'P','E','E','R','-','N','0','1'})||
     !receivedEquals(clientRam,std::vector<uint8_t>{'H','O','S','T','-','N','0','1'})){
    std::cerr<<"ordinal siguiente no se realineo\n";return 26;
  }

  // 64 KiB exactos requieren 55 fragmentos MTU-safe. Ademas los buffers
  // viven por encima de 8 MiB para verificar compatibilidad con un core de
  // RAM ampliada a 16 MiB.
  std::vector<uint8_t> largeHost(64*1024),largeClient(64*1024);
  for(size_t i=0;i<largeHost.size();++i){
    largeHost[i]=static_cast<uint8_t>((i*17+3)&0xff);
    largeClient[i]=static_cast<uint8_t>((i*29+11)&0xff);
  }
  constexpr size_t kExpandedSend=0x800000,kExpandedRecv=0x900000;
  hostBox.status=0;clientBox.status=0;
  host.dropNextDatagramsForTest(5);client.dropNextDatagramsForTest(3);
  request(clientRam,0,largeClient,static_cast<uint32_t>(largeHost.size()),0x8004F00D,
          kExpandedSend,kExpandedRecv);
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  request(hostRam,0,largeHost,static_cast<uint32_t>(largeClient.size()),0x8004F00D,
          kExpandedSend,kExpandedRecv);
  if(!waitForTransfer(hostBox,clientBox,std::chrono::seconds(10))||
     hostBox.recvSize!=largeClient.size()||clientBox.recvSize!=largeHost.size()||
     !receivedEquals(hostRam,largeClient,kExpandedRecv)||
     !receivedEquals(clientRam,largeHost,kExpandedRecv)){
    std::cerr<<"transferencia fragmentada de 64 KiB fallo: host="<<host.status()
      <<" client="<<client.status()<<"\n";return 20;
  }

  // Limites y punteros se rechazan antes de leer fuera de RAM.
  hostBox.status=0;
  hostBox.magic=kMagic;hostBox.version=kVersion;hostBox.command=kTransfer;
  hostBox.sendSize=64*1024+1;hostBox.recvCapacity=0;hostBox.sendAddress=kseg0(kDirectSendOffset);
  hostBox.recvAddress=kseg0(kDirectRecvOffset);publish(hostBox);
  const auto invalidSizeDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
  while(std::chrono::steady_clock::now()<invalidSizeDeadline&&hostBox.status!=4)
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  if(hostBox.status!=4){std::cerr<<"limite de 64 KiB no se aplico\n";return 21;}
  hostBox.status=0;hostBox.sendSize=64;hostBox.sendAddress=0x80FFFFE0;publish(hostBox);
  const auto invalidPointerDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
  while(std::chrono::steady_clock::now()<invalidPointerDeadline&&hostBox.status!=4)
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  if(hostBox.status!=4){std::cerr<<"puntero fuera de RAM no se rechazo\n";return 22;}
  hostBox.status=0;

  // En una sesion nueva el host entra primero y por eso queda como rol 1.
  {
    std::vector<uint8_t> reverseHostRam(2*1024*1024),reverseClientRam(2*1024*1024);
    mailbox(reverseHostRam).magic=kMagic;mailbox(reverseHostRam).version=kVersion;
    mailbox(reverseClientRam).magic=kMagic;mailbox(reverseClientRam).version=kVersion;
    NetBridge reverseHost,reverseClient;
    reverseHost.poll(reverseHostRam.data(),reverseHostRam.size());
    reverseClient.poll(reverseClientRam.data(),reverseClientRam.size());
    const auto reversePort=static_cast<uint16_t>(port+500);
    if(!reverseHost.host(reversePort)){std::cerr<<"host inverso fallo\n";return 8;}
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    if(!reverseClient.join("127.0.0.1",reversePort)){std::cerr<<"cliente inversa fallo\n";return 17;}
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
    while(std::chrono::steady_clock::now()<deadline&&
          (mailbox(reverseHostRam).flags!=kConnected||mailbox(reverseClientRam).flags!=kConnected))
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    requestRole(mailbox(reverseHostRam));
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    requestRole(mailbox(reverseClientRam));
    if(!waitForTransfer(mailbox(reverseHostRam),mailbox(reverseClientRam))||
       (mailbox(reverseHostRam).flags&0xff)!=2||(mailbox(reverseClientRam).flags&0xff)!=1){
      std::cerr<<"host authority must stay role 2 when host enters first\n";return 18;
    }
    // Normal menu -> level transitions MUST NOT cancel a connected session.
    const uint32_t linkedMenu=0x80080038,rootMenu=0x8007FEDC;
    std::memcpy(reverseClientRam.data()+0x89A0C,&linkedMenu,4);
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
    std::memcpy(reverseClientRam.data()+0x89A0C,&rootMenu,4);
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
    if(reverseHost.consumeReturnToMenu()||reverseClient.consumeReturnToMenu()){
      std::cerr<<"normal level transition incorrectly canceled session\n";return 63;
    }
    // The same menu return with a real Triangle intent must cancel both sides.
    std::memcpy(reverseClientRam.data()+0x89A0C,&linkedMenu,4);
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
    reverseClient.noteTrianglePress();
    std::memcpy(reverseClientRam.data()+0x89A0C,&rootMenu,4);
    bool hostReturned=false,clientReturned=false;
    const auto cancelDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(std::chrono::steady_clock::now()<cancelDeadline&&!(hostReturned&&clientReturned)){
      hostReturned=reverseHost.consumeReturnToMenu()||hostReturned;
      clientReturned=reverseClient.consumeReturnToMenu()||clientReturned;
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    if(!hostReturned||!clientReturned){std::cerr<<"guest cancellation did not reach both peers\n";return 62;}
  }

  for(uint32_t round=0;round<3;++round){
    const char* hostPayload=round==0?"HOST-FIFO-0":round==1?"HOST-FIFO-1":"HOST-FIFO-2";
    const char* clientPayload=round==0?"PEER-FIFO-0":round==1?"PEER-FIFO-1":"PEER-FIFO-2";
    hostBox.status=0;clientBox.status=0;
    requestText(clientRam,0,clientPayload,11,0x80051EBC);
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    requestText(hostRam,0,hostPayload,11,0x80051EBC);
    if(!waitForTransfer(hostBox,clientBox)||
       std::memcmp(hostRam.data()+kDirectRecvOffset,clientPayload,11)!=0||
       std::memcmp(clientRam.data()+kDirectRecvOffset,hostPayload,11)!=0){
      std::cerr<<"orden FIFO fallo en ronda "<<round<<"\n";return 10;
    }
  }

  // Modo opcional para validar en una sola sesion mas ticks que varios
  // minutos de gameplay real: TM3NetSmokeTest.exe --stress=9000.
  if(stressRounds){
    std::array<std::vector<uint8_t>,4> stressHost{{
      std::vector<uint8_t>(4),std::vector<uint8_t>(24),std::vector<uint8_t>(4),std::vector<uint8_t>(4)}};
    std::array<std::vector<uint8_t>,4> stressClient=stressHost;
    for(uint32_t round=0;round<stressRounds;++round){
      for(size_t part=0;part<4;++part){
        for(size_t byte=0;byte<stressHost[part].size();++byte){
          stressHost[part][byte]=static_cast<uint8_t>((round*17+part*31+byte)^0xA5);
          stressClient[part][byte]=static_cast<uint8_t>((round*29+part*13+byte)^0x5A);
        }
      }
      std::memcpy(stressHost[0].data(),&round,sizeof(round));
      const uint32_t remoteRound=round^0x80000000u;
      std::memcpy(stressClient[0].data(),&remoteRound,sizeof(remoteRound));
      if(round%113==37)host.dropNextResponsesForTest(2);
      if(round%157==71)client.dropNextRequestsForTest(1);
      hostBox.status=0;clientBox.status=0;
      requestBatch(clientRam,stressClient,batchSizes);
      requestBatch(hostRam,stressHost,batchSizes);
      if(!waitForTransfer(hostBox,clientBox,std::chrono::seconds(3))||
         readBatch(hostRam,batchSizes)!=concatenate(stressClient)||
         readBatch(clientRam,batchSizes)!=concatenate(stressHost)){
        std::cerr<<"stress de gameplay fallo en tick "<<round
          <<": host="<<host.status()<<" client="<<client.status()<<"\n";
        return 27;
      }
    }
    std::cout<<"Stress: "<<stressRounds<<" ticks batch consecutivos completados\n";
  }

  std::vector<uint8_t> disconnectHostRam(2*1024*1024),disconnectClientRam(2*1024*1024);
  mailbox(disconnectHostRam).magic=kMagic;mailbox(disconnectHostRam).version=kVersion;
  mailbox(disconnectClientRam).magic=kMagic;mailbox(disconnectClientRam).version=kVersion;
  NetBridge disconnectHost;
  disconnectHost.poll(disconnectHostRam.data(),disconnectHostRam.size());
  const auto disconnectPort=static_cast<uint16_t>(port+1000);
  if(!disconnectHost.host(disconnectPort)){std::cerr<<"host de desconexion fallo\n";return 11;}
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  {
    NetBridge disconnectClient;
    disconnectClient.poll(disconnectClientRam.data(),disconnectClientRam.size());
    if(!disconnectClient.join("127.0.0.1",disconnectPort)){
      std::cerr<<"cliente de desconexion fallo\n";return 12;
    }
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
    while(std::chrono::steady_clock::now()<deadline&&mailbox(disconnectHostRam).flags!=kConnected)
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    if(mailbox(disconnectHostRam).flags!=kConnected){
      std::cerr<<"conexion auxiliar no se publico\n";return 13;
    }
  }
  const auto disconnectDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
  while(std::chrono::steady_clock::now()<disconnectDeadline&&mailbox(disconnectHostRam).flags!=0)
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  if(mailbox(disconnectHostRam).flags!=0){std::cerr<<"flags no retiro peer desconectado\n";return 14;}

  wchar_t wakeMode[8]{};
  const bool expectedWake=GetEnvironmentVariableW(L"TM3O_LINK_UDP_WAKE",wakeMode,8)==1&&wakeMode[0]==L'1';
  const auto wakes=host.udpWakeCountForTest()+client.udpWakeCountForTest();
  if(expectedWake!=(wakes>0)){
    std::cerr<<"UDP wake mode not exercised: expected="<<expectedWake<<" wakes="<<wakes<<"\n";
    return 28;
  }
  std::cout<<"UDP event wakes: "<<wakes<<"\n";
  std::cout<<"OK: mailbox v5/protocolo v6, batch 36 B, ordinal por callSite, "
    "perdida/reordenamiento, fragmentacion/reensamble 64 KiB, buffers sobre 8 MiB "
    "en RAM de 16 MiB, codecave RNGCaller, roles, FIFO, 4/0, desconexion y secuencias desalineadas "
    "confirmados en 127.0.0.1:"<<port<<"\n";
  return 0;
}
