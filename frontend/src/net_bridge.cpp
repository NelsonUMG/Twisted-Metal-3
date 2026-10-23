#include "net_bridge.hpp"
#include <ws2tcpip.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <random>
#include <sstream>

namespace {
bool initWsa(){
  static const bool initialized=[](){WSADATA data{};return WSAStartup(MAKEWORD(2,2),&data)==0;}();
  return initialized;
}

bool tcpPeerClosed(SOCKET socket){
  fd_set readable;
  FD_ZERO(&readable);
  FD_SET(socket,&readable);
  timeval timeout{};
  const int ready=select(0,&readable,nullptr,nullptr,&timeout);
  if(ready==SOCKET_ERROR)return true;
  if(ready==0)return false;
  char byte=0;
  const int peeked=recv(socket,&byte,1,MSG_PEEK);
  if(peeked==0)return true;
  if(peeked==SOCKET_ERROR)return WSAGetLastError()!=WSAEWOULDBLOCK;
  return false;
}

bool sequenceBefore(uint32_t lhs,uint32_t rhs){
  return static_cast<int32_t>(lhs-rhs)<0;
}

uint32_t firstWord(const uint8_t* data,size_t size){
  uint32_t value=0;
  if(size==0)return value;
  std::memcpy(&value,data,std::min<size_t>(size,sizeof(value)));
  return value;
}
}

NetBridge::~NetBridge(){
  worker_.request_stop();
  closeSockets();
  if(worker_.joinable())worker_.join();
}

bool NetBridge::host(uint16_t port){
  if(!initWsa()||worker_.joinable())return false;
  openTrace(L"TM3Online_Oscar.trace.log");
  transportHost_=true;
  localRole_.store(0,std::memory_order_release);
  setStatus("iniciando host TCP/UDP");
  worker_=std::jthread([this,port](std::stop_token stop){workerHost(port,stop);});
  return true;
}

bool NetBridge::join(const std::string& host,uint16_t port){
  if(!initWsa()||worker_.joinable())return false;
  openTrace(L"TM3Online_Sofia.trace.log");
  transportHost_=false;
  localRole_.store(0,std::memory_order_release);
  setStatus("conectando por TCP");
  worker_=std::jthread([this,host,port](std::stop_token stop){workerJoin(host,port,stop);});
  return true;
}

void NetBridge::poll(uint8_t* ram,size_t ramSize){
  ramSize_.store(ramSize,std::memory_order_release);
  ram_.store(ram,std::memory_order_release);
}

std::string NetBridge::status() const{
  std::scoped_lock lock(mutex_);
  std::ostringstream output;
  output<<status_<<" | game-role="<<localRole_.load(std::memory_order_acquire)
    <<" ram="<<(ramSize_.load(std::memory_order_acquire)/(1024*1024))<<"MiB"
    <<" role-req="<<roleRequests_.load()
    <<" req="<<requests_.load()
    <<" io="<<lastSendSize_.load()<<"/"<<lastRecvCapacity_.load()
    <<" UDP tx="<<udpSent_.load()<<" rx="<<udpReceived_.load()
    <<" ok="<<completed_.load()<<" err="<<errors_.load()<<" seq="<<lastSequence_.load()
    <<" ord="<<lastOrdinal_.load()<<">"<<lastRemoteOrdinal_.load()
    <<" retry="<<pendingRetransmissions_.load()
    <<" call="<<std::hex<<std::uppercase<<lastCallSite_.load()
    <<" word="<<lastSendWord_.load()<<">"<<lastRecvWord_.load();
  return output.str();
}

void NetBridge::setStatus(std::string value){
  std::scoped_lock lock(mutex_);
  status_=std::move(value);
}

void NetBridge::openTrace(const wchar_t* filename){
  std::array<wchar_t,32768> modulePath{};
  const DWORD length=GetModuleFileNameW(nullptr,modulePath.data(),static_cast<DWORD>(modulePath.size()));
  if(length==0)return;
  auto path=std::filesystem::path(std::wstring(modulePath.data(),length)).parent_path()/filename;
  trace_.open(path,std::ios::out|std::ios::trunc);
}

void NetBridge::trace(std::string line){
  if(!trace_||traceEvents_>=kTraceLimit)return;
  trace_<<line<<'\n';
  ++traceEvents_;
  if(traceEvents_%kTraceFlushInterval==0)trace_.flush();
}

void NetBridge::closeSockets(){
  if(udp_!=INVALID_SOCKET){closesocket(udp_);udp_=INVALID_SOCKET;}
  if(tcp_!=INVALID_SOCKET){closesocket(tcp_);tcp_=INVALID_SOCKET;}
  if(listen_!=INVALID_SOCKET){closesocket(listen_);listen_=INVALID_SOCKET;}
}

bool NetBridge::openUdp(uint16_t requestedPort,uint16_t& boundPort){
  udp_=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
  if(udp_==INVALID_SOCKET)return false;
  int socketBuffer=1<<20;
  setsockopt(udp_,SOL_SOCKET,SO_RCVBUF,reinterpret_cast<const char*>(&socketBuffer),sizeof(socketBuffer));
  setsockopt(udp_,SOL_SOCKET,SO_SNDBUF,reinterpret_cast<const char*>(&socketBuffer),sizeof(socketBuffer));
  sockaddr_in local{};
  local.sin_family=AF_INET;
  local.sin_addr.s_addr=htonl(INADDR_ANY);
  local.sin_port=htons(requestedPort);
  if(bind(udp_,reinterpret_cast<const sockaddr*>(&local),sizeof(local))!=0)return false;
  int length=sizeof(local);
  if(getsockname(udp_,reinterpret_cast<sockaddr*>(&local),&length)!=0)return false;
  boundPort=ntohs(local.sin_port);
  u_long nonBlocking=1;
  return ioctlsocket(udp_,FIONBIO,&nonBlocking)==0;
}

void NetBridge::workerHost(uint16_t port,std::stop_token stop){
  uint16_t udpPort=0;
  if(!openUdp(port,udpPort)){setStatus("error abriendo UDP");return;}
  listen_=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
  if(listen_==INVALID_SOCKET){setStatus("error abriendo TCP");return;}
  int yes=1;
  setsockopt(listen_,SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<const char*>(&yes),sizeof(yes));
  sockaddr_in local{};
  local.sin_family=AF_INET;
  local.sin_addr.s_addr=htonl(INADDR_ANY);
  local.sin_port=htons(port);
  if(bind(listen_,reinterpret_cast<const sockaddr*>(&local),sizeof(local))!=0||listen(listen_,1)!=0){
    setStatus("error reservando puerto TCP");return;
  }
  setStatus("esperando jugador por TCP");
  sockaddr_in remote{};
  int remoteLength=sizeof(remote);
  tcp_=accept(listen_,reinterpret_cast<sockaddr*>(&remote),&remoteLength);
  if(tcp_==INVALID_SOCKET||stop.stop_requested())return;
  int one=1;
  setsockopt(tcp_,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<const char*>(&one),sizeof(one));

  Control hello{};
  if(!recvAll(&hello,sizeof(hello))||hello.magic!=kMagic||hello.version!=kProtocolVersion||
     hello.kind!=kHello||hello.udpPort==0||hello.udpPort>0xFFFFu){
    setStatus("handshake TCP invalido");return;
  }
  peerUdp_=remote;
  peerUdp_.sin_port=htons(static_cast<uint16_t>(hello.udpPort));
  std::random_device random;
  session_=(static_cast<uint64_t>(random())<<32)|random();
  if(session_==0)session_=1;
  const Control accept{kMagic,kProtocolVersion,kAccept,udpPort,0,session_};
  if(!sendAll(&accept,sizeof(accept))){setStatus("fallo enviando handshake TCP");return;}
  connected_.store(true,std::memory_order_release);
  setStatus("conectado: TCP sesion / UDP gameplay");
  sessionLoop(stop);
}

void NetBridge::workerJoin(std::string host,uint16_t port,std::stop_token stop){
  uint16_t udpPort=0;
  if(!openUdp(0,udpPort)){setStatus("error abriendo UDP");return;}
  addrinfo hints{};
  hints.ai_family=AF_INET;
  hints.ai_socktype=SOCK_STREAM;
  hints.ai_protocol=IPPROTO_TCP;
  addrinfo* addresses=nullptr;
  const auto service=std::to_string(port);
  if(getaddrinfo(host.c_str(),service.c_str(),&hints,&addresses)!=0){setStatus("host no encontrado");return;}
  for(auto* address=addresses;address;address=address->ai_next){
    tcp_=socket(address->ai_family,address->ai_socktype,address->ai_protocol);
    if(tcp_!=INVALID_SOCKET&&connect(tcp_,address->ai_addr,static_cast<int>(address->ai_addrlen))==0)break;
    if(tcp_!=INVALID_SOCKET)closesocket(tcp_);
    tcp_=INVALID_SOCKET;
  }
  freeaddrinfo(addresses);
  if(tcp_==INVALID_SOCKET||stop.stop_requested()){setStatus("no se pudo conectar por TCP");return;}
  int one=1;
  setsockopt(tcp_,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<const char*>(&one),sizeof(one));
  int peerLength=sizeof(peerUdp_);
  if(getpeername(tcp_,reinterpret_cast<sockaddr*>(&peerUdp_),&peerLength)!=0){setStatus("peer TCP invalido");return;}
  const Control hello{kMagic,kProtocolVersion,kHello,udpPort,0,0};
  Control accept{};
  if(!sendAll(&hello,sizeof(hello))||!recvAll(&accept,sizeof(accept))||
     accept.magic!=kMagic||accept.version!=kProtocolVersion||accept.kind!=kAccept||
     accept.udpPort==0||accept.udpPort>0xFFFFu||accept.session==0){
    setStatus("handshake TCP invalido");return;
  }
  peerUdp_.sin_port=htons(static_cast<uint16_t>(accept.udpPort));
  session_=accept.session;
  connected_.store(true,std::memory_order_release);
  setStatus("conectado: TCP sesion / UDP gameplay");
  sessionLoop(stop);
}

void NetBridge::sessionLoop(std::stop_token stop){
  while(!stop.stop_requested()){
    processTcpControls();
    receiveDatagrams();
    processMailbox();
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  connected_.store(false,std::memory_order_release);
  setStatus("desconectado");
}

void NetBridge::processTcpControls(){
  if(tcp_==INVALID_SOCKET)return;
  for(;;){
    u_long available=0;
    if(ioctlsocket(tcp_,FIONREAD,&available)!=0){
      connected_.store(false,std::memory_order_release);
      setStatus("error consultando sesion TCP");
      return;
    }
    if(available<sizeof(Control)){
      // SIO_STAT.7 reflejaba el DTR remoto como una señal de nivel. TCP debe
      // retirar el equivalente TM3O.flags cuando el peer cierra la sesión,
      // incluso si no quedó ningún Control pendiente para leer.
      if(tcpPeerClosed(tcp_)){
        connected_.store(false,std::memory_order_release);
        setStatus("peer TCP desconectado");
      }
      return;
    }
    Control control{};
    if(!recvAll(&control,sizeof(control))){
      connected_.store(false,std::memory_order_release);
      setStatus("peer TCP desconectado");
      return;
    }
    if(control.magic!=kMagic||control.version!=kProtocolVersion||control.session!=session_)continue;
    if(transportHost_&&control.kind==kRoleReady){
      remoteRoleRound_=control.udpPort;
      remoteRoleWaiting_=true;
      remoteRoleOrder_=++roleOrder_;
      trace("ROLE_READY remoto round="+std::to_string(remoteRoleRound_)+
        " order="+std::to_string(remoteRoleOrder_));
      assignRolesIfReady();
    }else if(!transportHost_&&control.kind==kRoleAssign&&localRoleWaiting_&&
             control.udpPort==localRoleRound_&&(control.reserved==1||control.reserved==2)){
      localRole_.store(static_cast<uint16_t>(control.reserved),std::memory_order_release);
      localRoleWaiting_=false;
      trace("ROLE_ASSIGN recibido round="+std::to_string(control.udpPort)+
        " role="+std::to_string(control.reserved));
    }
  }
}

void NetBridge::receiveDatagrams(){
  std::array<uint8_t,sizeof(Wire)+kFragmentPayload> datagram{};
  for(;;){
    sockaddr_in sender{};
    int senderLength=sizeof(sender);
    const int received=recvfrom(udp_,reinterpret_cast<char*>(datagram.data()),
      static_cast<int>(datagram.size()),0,reinterpret_cast<sockaddr*>(&sender),&senderLength);
    if(received<0){
      const int error=WSAGetLastError();
      if(error==WSAEWOULDBLOCK)return;
      return;
    }
    if(static_cast<size_t>(received)<sizeof(Wire)||sender.sin_addr.s_addr!=peerUdp_.sin_addr.s_addr||
       sender.sin_port!=peerUdp_.sin_port)continue;
    Wire wire{};
    std::memcpy(&wire,datagram.data(),sizeof(wire));
    if(wire.magic!=kMagic||wire.version!=kProtocolVersion||wire.session!=session_||wire.ordinal==0||
       (wire.command!=kTransfer&&wire.command!=kBatchTransfer)||
       wire.payloadSize>kMaxPayload||wire.expectedSize>kMaxPayload||
       wire.fragmentSize>kFragmentPayload||
       static_cast<size_t>(received)!=sizeof(Wire)+wire.fragmentSize)continue;
    const uint32_t fragmentCount=wire.payloadSize==0?1u:
      static_cast<uint32_t>((wire.payloadSize+kFragmentPayload-1)/kFragmentPayload);
    if(wire.payloadSize==0){
      if(wire.fragmentOffset!=0||wire.fragmentSize!=0)continue;
    }else{
      if(wire.fragmentOffset%kFragmentPayload!=0||wire.fragmentOffset>=wire.payloadSize)continue;
      const uint32_t expectedFragment=static_cast<uint32_t>(std::min<size_t>(
        kFragmentPayload,wire.payloadSize-wire.fragmentOffset));
      if(wire.fragmentSize!=expectedFragment)continue;
    }
    udpReceived_.fetch_add(1,std::memory_order_relaxed);
    const bool request=wire.replyTo==0;
    const uint32_t key=request?wire.sequence:wire.replyTo;
    auto& destination=request?incomingRequests_:incomingResponses_;
    auto found=destination.find(key);
    if(found==destination.end()){
      Incoming incoming{};
      incoming.command=wire.command;
      incoming.sequence=wire.sequence;
      incoming.replyTo=wire.replyTo;
      incoming.ordinal=wire.ordinal;
      incoming.expectedSize=wire.expectedSize;
      incoming.callSite=wire.callSite;
      incoming.crc=wire.crc;
      incoming.payload.resize(wire.payloadSize);
      incoming.receivedFragments.assign(fragmentCount,0);
      incoming.fragmentCount=fragmentCount;
      found=destination.emplace(key,std::move(incoming)).first;
    }
    auto& incoming=found->second;
    if(incoming.command!=wire.command||incoming.sequence!=wire.sequence||
       incoming.replyTo!=wire.replyTo||incoming.ordinal!=wire.ordinal||
       incoming.expectedSize!=wire.expectedSize||
       incoming.callSite!=wire.callSite||incoming.crc!=wire.crc||
       incoming.payload.size()!=wire.payloadSize||incoming.fragmentCount!=fragmentCount){
      destination.erase(found);
      continue;
    }
    if(incoming.complete){
      if(request){
        const auto replay=responseReplay_.find(wire.sequence);
        if(replay!=responseReplay_.end())sendPacket(replay->second);
      }
      continue;
    }
    const uint32_t fragmentIndex=wire.payloadSize==0?0u:
      static_cast<uint32_t>(wire.fragmentOffset/kFragmentPayload);
    if(fragmentIndex>=incoming.receivedFragments.size()){
      destination.erase(found);
      continue;
    }
    if(!incoming.receivedFragments[fragmentIndex]){
      if(wire.fragmentSize)std::memcpy(incoming.payload.data()+wire.fragmentOffset,
        datagram.data()+sizeof(Wire),wire.fragmentSize);
      incoming.receivedFragments[fragmentIndex]=1;
      ++incoming.receivedCount;
    }
    if(incoming.receivedCount!=incoming.fragmentCount)continue;
    if(crc32(incoming.payload.data(),incoming.payload.size())!=incoming.crc){
      destination.erase(found);
      continue;
    }
    incoming.complete=true;
    if(request){
      const auto replay=responseReplay_.find(wire.sequence);
      if(replay!=responseReplay_.end()){
        sendPacket(replay->second);
        destination.erase(found);
        continue;
      }
    }
    if(destination.size()>64)destination.erase(destination.begin());
  }
}

bool NetBridge::beginRoleNegotiation(){
  roleRequests_.fetch_add(1,std::memory_order_relaxed);

  // El rol pertenece a la sesion enlazada, no a cada reentrada de
  // 0x80047D3C. El SIO fisico conserva DTR/DSR y el estado de ambos extremos
  // mientras el cable sigue conectado. TM3 puede volver al inicio de esta
  // rutina si esta repitiendo el intercambio del rol anterior o del token
  // 0x45; borrar aqui un rol ya confirmado iniciaba otra ronda y dejaba a
  // ambas consolas negociando indefinidamente.
  const uint16_t assignedRole=localRole_.load(std::memory_order_acquire);
  if(assignedRole==1||assignedRole==2){
    trace("ROLE_REUSE role="+std::to_string(assignedRole)+
      " round="+std::to_string(localRoleRound_));
    return true;
  }
  if(localRoleWaiting_){
    trace("ROLE_REUSE waiting round="+std::to_string(localRoleRound_));
    return true;
  }

  localRole_.store(0,std::memory_order_release);
  ++localRoleRound_;
  if(localRoleRound_==0)++localRoleRound_;
  localRoleWaiting_=true;
  localRoleOrder_=++roleOrder_;
  trace("ROLE_BEGIN local round="+std::to_string(localRoleRound_)+
    " order="+std::to_string(localRoleOrder_)+" remoteRound="+std::to_string(remoteRoleRound_));
  if(transportHost_){
    assignRolesIfReady();
    return true;
  }
  const Control ready{kMagic,kProtocolVersion,kRoleReady,localRoleRound_,0,session_};
  return sendAll(&ready,sizeof(ready));
}

void NetBridge::assignRolesIfReady(){
  if(!transportHost_||!localRoleWaiting_||!remoteRoleWaiting_||
     localRoleRound_!=remoteRoleRound_)return;
  // La primera consola que entra queda esperando como secundaria. La segunda
  // recibe la autoridad de configuracion, igual que con dos PS1 fisicas.
  const uint16_t localRole=localRoleOrder_<remoteRoleOrder_?1:2;
  const uint16_t remoteRole=localRole==1?2:1;
  trace("ROLE_SEND round="+std::to_string(localRoleRound_)+" local="+
    std::to_string(localRole)+" remote="+std::to_string(remoteRole)+" orders="+
    std::to_string(localRoleOrder_)+"/"+std::to_string(remoteRoleOrder_));
  const Control assignment{kMagic,kProtocolVersion,kRoleAssign,localRoleRound_,remoteRole,session_};
  if(!sendAll(&assignment,sizeof(assignment)))return;
  localRole_.store(localRole,std::memory_order_release);
  localRoleWaiting_=false;
  remoteRoleWaiting_=false;
}

void NetBridge::processMailbox(){
  auto* ram=ram_.load(std::memory_order_acquire);
  const size_t ramSize=ramSize_.load(std::memory_order_acquire);
  if(!ram||ramSize<kMailboxOffset+sizeof(Mailbox))return;
  auto* mailbox=reinterpret_cast<Mailbox*>(ram+kMailboxOffset);
  if(mailbox->magic!=kMagic||mailbox->version!=kMailboxVersion)return;
  const bool connected=connected_.load(std::memory_order_acquire);
  const uint16_t role=localRole_.load(std::memory_order_acquire);
  const uint16_t ramFlag=ramSize>=16*1024*1024?kExpandedRamFlag:0;
  writeMailboxFlags(mailbox,connected?static_cast<uint16_t>(kConnectedFlag|ramFlag|role):ramFlag);
  const auto fail=[this,mailbox](){
    pending_.reset();
    pendingRetransmissions_.store(0,std::memory_order_relaxed);
    errors_.fetch_add(1,std::memory_order_relaxed);
    writeMailboxStatus(mailbox,4);
  };
  const auto buildPending=[ram,ramSize,mailbox](Pending& pending){
    const auto appendSend=[ram,ramSize,&pending](uint32_t address,uint32_t size){
      size_t offset=0;
      if(!translateRamRange(ramSize,address,size,offset))return false;
      if(size)pending.payload.insert(pending.payload.end(),ram+offset,ram+offset+size);
      return true;
    };
    const auto appendReceive=[ramSize,&pending](uint32_t address,uint32_t size){
      size_t offset=0;
      if(!translateRamRange(ramSize,address,size,offset))return false;
      if(size)pending.recvRanges.push_back(RamRange{offset,size});
      return true;
    };
    pending.payload.reserve(mailbox->sendSize);
    if(mailbox->command==kTransfer){
      return appendSend(mailbox->sendAddress,mailbox->sendSize)&&
        appendReceive(mailbox->recvAddress,mailbox->recvCapacity)&&
        pending.payload.size()==mailbox->sendSize;
    }
    if(mailbox->command!=kBatchTransfer||mailbox->sendSegmentCount>4||
       mailbox->recvSegmentCount>4)return false;
    uint64_t sendTotal=0,recvTotal=0;
    for(uint32_t index=0;index<mailbox->sendSegmentCount;++index){
      const auto& segment=mailbox->sendSegments[index];
      sendTotal+=segment.size;
      if(sendTotal>kMaxPayload||!appendSend(segment.address,segment.size))return false;
    }
    for(uint32_t index=0;index<mailbox->recvSegmentCount;++index){
      const auto& segment=mailbox->recvSegments[index];
      recvTotal+=segment.size;
      if(recvTotal>kMaxPayload||!appendReceive(segment.address,segment.size))return false;
    }
    return sendTotal==mailbox->sendSize&&recvTotal==mailbox->recvCapacity&&
      pending.payload.size()==mailbox->sendSize;
  };
  const auto scatterReceive=[ram](const Pending& pending,const std::vector<uint8_t>& payload){
    size_t position=0;
    for(const auto& range:pending.recvRanges){
      if(position>payload.size())return false;
      const size_t count=std::min<size_t>(range.size,payload.size()-position);
      if(count)std::memcpy(ram+range.offset,payload.data()+position,count);
      position+=count;
      if(position==payload.size())break;
    }
    return position==payload.size();
  };

  uint16_t mailboxStatus=readMailboxStatus(mailbox);
  if(!connected&&(mailboxStatus==1||mailboxStatus==2)){
    fail();return;
  }
  if(mailboxStatus==1){
    if(mailbox->command==kRoleRequest){
      pending_.reset();
      pendingRetransmissions_.store(0,std::memory_order_relaxed);
      if(!beginRoleNegotiation()){fail();return;}
      writeMailboxFlags(mailbox,static_cast<uint16_t>(kConnectedFlag|ramFlag));
      writeMailboxStatus(mailbox,2);
      mailboxStatus=2;
    }else if((mailbox->command!=kTransfer&&mailbox->command!=kBatchTransfer)||
             mailbox->sendSize>kMaxPayload||mailbox->recvCapacity>kMaxPayload){
      fail();return;
    }else{
      Pending pending{};
      pending.command=mailbox->command;
      pending.replyTo=0;
      pending.expectedSize=mailbox->recvCapacity;
      pending.callSite=mailbox->callSite;
      auto& ordinal=callOrdinals_[pending.callSite];
      ++ordinal;
      if(ordinal==0)++ordinal;
      pending.ordinal=ordinal;
      if(!buildPending(pending)){fail();return;}
      ++nextSequence_;
      if(nextSequence_==0)++nextSequence_;
      mailbox->sequence=nextSequence_;
      pending.sequence=mailbox->sequence;
      pending.lastSent=std::chrono::steady_clock::now();
      requests_.fetch_add(1,std::memory_order_relaxed);
      lastSendSize_.store(mailbox->sendSize,std::memory_order_relaxed);
      lastRecvCapacity_.store(mailbox->recvCapacity,std::memory_order_relaxed);
      lastCallSite_.store(mailbox->callSite,std::memory_order_relaxed);
      lastOrdinal_.store(pending.ordinal,std::memory_order_relaxed);
      pendingRetransmissions_.store(0,std::memory_order_relaxed);
      lastSendWord_.store(firstWord(pending.payload.data(),pending.payload.size()),std::memory_order_relaxed);
      {
        std::ostringstream line;
        line<<"TX seq="<<mailbox->sequence<<" ord="<<pending.ordinal
          <<" call="<<std::hex<<std::uppercase<<mailbox->callSite
          <<" sizes="<<std::dec<<mailbox->sendSize<<"/"<<mailbox->recvCapacity
          <<" mode="<<(mailbox->command==kBatchTransfer?"BATCH":"DIRECT")
          <<" word="<<std::hex<<firstWord(pending.payload.data(),pending.payload.size());
        trace(line.str());
      }
      pending_=std::move(pending);
      if(!sendPacket(*pending_)){fail();return;}
      writeMailboxStatus(mailbox,2);
      mailboxStatus=2;
    }
  }

  if(mailboxStatus!=2)return;
  if(mailbox->command==kRoleRequest){
    const uint16_t assignedRole=localRole_.load(std::memory_order_acquire);
    if(assignedRole==0)return;
    mailbox->recvSize=0;
    writeMailboxFlags(mailbox,static_cast<uint16_t>(kConnectedFlag|ramFlag|assignedRole));
    writeMailboxStatus(mailbox,3);
    return;
  }
  if(!pending_||pending_->sequence!=mailbox->sequence){fail();return;}
  // Una respuesta identifica exactamente nuestra solicitud mediante replyTo.
  // No exige que el contador de secuencia remoto coincida con el local.
  auto foundResponse=incomingResponses_.find(mailbox->sequence);
  if(foundResponse!=incomingResponses_.end()&&foundResponse->second.complete){
    if(foundResponse->second.command!=mailbox->command||
       foundResponse->second.ordinal!=pending_->ordinal||
       foundResponse->second.callSite!=pending_->callSite||
       foundResponse->second.payload.size()>mailbox->recvCapacity||
       pending_->payload.size()>foundResponse->second.expectedSize){
      incomingResponses_.erase(foundResponse);fail();return;
    }
    const uint32_t remoteSequence=foundResponse->second.sequence;
    if(!scatterReceive(*pending_,foundResponse->second.payload)){
      incomingResponses_.erase(foundResponse);fail();return;
    }
    lastRecvWord_.store(firstWord(foundResponse->second.payload.data(),foundResponse->second.payload.size()),
      std::memory_order_relaxed);
    lastRemoteOrdinal_.store(foundResponse->second.ordinal,std::memory_order_relaxed);
    {
      std::ostringstream line;
      line<<"RX_RESPONSE seq="<<mailbox->sequence<<" ord="<<pending_->ordinal
        <<" remote-ord="<<foundResponse->second.ordinal
        <<" call="<<std::hex<<std::uppercase<<mailbox->callSite
        <<" word="<<firstWord(foundResponse->second.payload.data(),foundResponse->second.payload.size());
      trace(line.str());
    }
    mailbox->recvSize=static_cast<uint32_t>(foundResponse->second.payload.size());
    lastSequence_.store(mailbox->sequence,std::memory_order_relaxed);
    completed_.fetch_add(1,std::memory_order_relaxed);
    incomingResponses_.erase(foundResponse);
    // La respuesta y el REQUEST del par pueden llegar juntos. Ambos describen
    // la misma operacion remota; conservar el REQUEST lo haria parecer una
    // solicitud nueva en la siguiente llamada MIPS.
    incomingRequests_.erase(remoteSequence);
    pending_.reset();
    pendingRetransmissions_.store(0,std::memory_order_relaxed);
    writeMailboxStatus(mailbox,3);
    return;
  }

  // Si todavia no llego una respuesta, cualquier REQUEST remoto compatible
  // puede completar la operacion. El juego es sincrono, pero cada PS1 puede
  // haber ejecutado una llamada adicional y por eso sus secuencias divergen.
  auto foundRequest=incomingRequests_.end();
  for(auto it=incomingRequests_.begin();it!=incomingRequests_.end();++it){
    if(it->second.complete&&it->second.command==mailbox->command&&
       it->second.ordinal==pending_->ordinal&&
       it->second.callSite==pending_->callSite&&
       it->second.payload.size()<=mailbox->recvCapacity&&
       pending_->payload.size()<=it->second.expectedSize&&
       (foundRequest==incomingRequests_.end()||
        sequenceBefore(it->second.sequence,foundRequest->second.sequence))){
      // El SIO físico entrega un flujo FIFO. Si UDP dejó más de una
      // solicitud compatible en cola, conserva el orden lógico del emisor.
      foundRequest=it;
    }
  }
  if(foundRequest!=incomingRequests_.end()){
    Pending response=*pending_;
    response.replyTo=foundRequest->second.sequence;
    response.ordinal=foundRequest->second.ordinal;
    response.lastSent=std::chrono::steady_clock::now();
    if(!sendPacket(response)){incomingRequests_.erase(foundRequest);fail();return;}
    responseReplay_[foundRequest->second.sequence]=std::move(response);
    if(responseReplay_.size()>64)responseReplay_.erase(responseReplay_.begin());
    if(!scatterReceive(*pending_,foundRequest->second.payload)){
      incomingRequests_.erase(foundRequest);fail();return;
    }
    lastRecvWord_.store(firstWord(foundRequest->second.payload.data(),foundRequest->second.payload.size()),
      std::memory_order_relaxed);
    lastRemoteOrdinal_.store(foundRequest->second.ordinal,std::memory_order_relaxed);
    {
      std::ostringstream line;
      line<<"RX_REQUEST seq="<<mailbox->sequence<<" ord="<<pending_->ordinal
        <<" remote-ord="<<foundRequest->second.ordinal
        <<" call="<<std::hex<<std::uppercase<<mailbox->callSite
        <<" word="<<firstWord(foundRequest->second.payload.data(),foundRequest->second.payload.size());
      trace(line.str());
    }
    mailbox->recvSize=static_cast<uint32_t>(foundRequest->second.payload.size());
    lastSequence_.store(mailbox->sequence,std::memory_order_relaxed);
    completed_.fetch_add(1,std::memory_order_relaxed);
    incomingRequests_.erase(foundRequest);
    pending_.reset();
    pendingRetransmissions_.store(0,std::memory_order_relaxed);
    writeMailboxStatus(mailbox,3);
    return;
  }

  const auto now=std::chrono::steady_clock::now();
  if(now-pending_->lastSent>=kRetransmitDelay){
    if(!sendPacket(*pending_)){fail();return;}
    pending_->lastSent=now;
    ++pending_->retransmissions;
    pendingRetransmissions_.store(pending_->retransmissions,std::memory_order_relaxed);
    if(pending_->retransmissions==1||
       (pending_->retransmissions&(pending_->retransmissions-1))==0){
      trace("RETRY seq="+std::to_string(pending_->sequence)+
        " ord="+std::to_string(pending_->ordinal)+
        " count="+std::to_string(pending_->retransmissions));
    }
  }
}

bool NetBridge::sendPacket(const Pending& packet){
  if(udp_==INVALID_SOCKET||packet.payload.size()>kMaxPayload||packet.expectedSize>kMaxPayload)return false;
  std::array<uint8_t,sizeof(Wire)+kFragmentPayload> datagram{};
  const uint32_t payloadSize=static_cast<uint32_t>(packet.payload.size());
  const uint32_t fragmentCount=payloadSize==0?1u:
    static_cast<uint32_t>((payloadSize+kFragmentPayload-1)/kFragmentPayload);
  const uint32_t payloadCrc=crc32(packet.payload.data(),packet.payload.size());
  for(uint32_t fragmentIndex=0;fragmentIndex<fragmentCount;++fragmentIndex){
    const uint32_t fragmentOffset=fragmentIndex*static_cast<uint32_t>(kFragmentPayload);
    const uint32_t fragmentSize=payloadSize==0?0u:static_cast<uint32_t>(
      std::min<size_t>(kFragmentPayload,payloadSize-fragmentOffset));
#ifdef TM3ONLINE_TESTING
    bool drop=false;
    const auto consumeDrop=[](std::atomic<uint32_t>& counter){
      uint32_t drops=counter.load(std::memory_order_acquire);
      while(drops!=0){
        if(counter.compare_exchange_weak(drops,drops-1,std::memory_order_acq_rel))return true;
      }
      return false;
    };
    drop=consumeDrop(testDrops_);
    if(!drop&&packet.replyTo==0)drop=consumeDrop(testRequestDrops_);
    if(!drop&&packet.replyTo!=0)drop=consumeDrop(testResponseDrops_);
    if(drop)continue;
#endif
    const Wire wire{kMagic,kProtocolVersion,packet.command,session_,packet.sequence,
      packet.replyTo,packet.ordinal,payloadSize,packet.expectedSize,packet.callSite,payloadCrc,
      fragmentOffset,fragmentSize};
    std::memcpy(datagram.data(),&wire,sizeof(wire));
    if(fragmentSize)std::memcpy(datagram.data()+sizeof(wire),
      packet.payload.data()+fragmentOffset,fragmentSize);
    const size_t size=sizeof(wire)+fragmentSize;
    const int sent=sendto(udp_,reinterpret_cast<const char*>(datagram.data()),static_cast<int>(size),0,
      reinterpret_cast<const sockaddr*>(&peerUdp_),sizeof(peerUdp_));
    if(sent!=static_cast<int>(size))return false;
    udpSent_.fetch_add(1,std::memory_order_relaxed);
  }
  return true;
}

bool NetBridge::sendAll(const void* data,size_t size){
  auto* bytes=static_cast<const char*>(data);
  while(size){
    const int sent=send(tcp_,bytes,static_cast<int>(std::min<size_t>(size,1u<<20)),0);
    if(sent<=0)return false;
    bytes+=sent;size-=static_cast<size_t>(sent);
  }
  return true;
}

bool NetBridge::recvAll(void* data,size_t size){
  auto* bytes=static_cast<char*>(data);
  while(size){
    const int received=recv(tcp_,bytes,static_cast<int>(std::min<size_t>(size,1u<<20)),0);
    if(received<=0)return false;
    bytes+=received;size-=static_cast<size_t>(received);
  }
  return true;
}

uint16_t NetBridge::readMailboxStatus(const Mailbox* mailbox){
  MemoryBarrier();
  const auto value=*reinterpret_cast<const volatile uint16_t*>(&mailbox->status);
  MemoryBarrier();
  return value;
}

void NetBridge::writeMailboxStatus(Mailbox* mailbox,uint16_t status){
  MemoryBarrier();
  *reinterpret_cast<volatile uint16_t*>(&mailbox->status)=status;
  MemoryBarrier();
}

void NetBridge::writeMailboxFlags(Mailbox* mailbox,uint16_t flags){
  MemoryBarrier();
  *reinterpret_cast<volatile uint16_t*>(&mailbox->flags)=flags;
  MemoryBarrier();
}

bool NetBridge::translateRamRange(size_t ramSize,uint32_t address,size_t size,size_t& offset){
  if(size==0){offset=0;return true;}
  const uint32_t segment=address&0xE0000000u;
  uint32_t physical=0;
  if(segment==0x80000000u||segment==0xA0000000u)physical=address&0x1FFFFFFFu;
  else if(address<ramSize)physical=address;
  else return false;
  offset=physical;
  return offset<=ramSize&&size<=ramSize-offset;
}

uint32_t NetBridge::crc32(const uint8_t* data,size_t size){
  uint32_t crc=~0u;
  for(size_t i=0;i<size;++i){
    crc^=data[i];
    for(int bit=0;bit<8;++bit)crc=(crc>>1)^(0xEDB88320u&-static_cast<int>(crc&1));
  }
  return ~crc;
}
