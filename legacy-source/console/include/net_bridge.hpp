#pragma once
#include <winsock2.h>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

class NetBridge {
public:
  ~NetBridge();
  bool host(uint16_t port);
  bool join(const std::string& host,uint16_t port);
  void poll(uint8_t* ram,size_t ramSize);
  std::string status() const;
  bool connected() const{return connected_.load(std::memory_order_acquire);}
  void requestReturnToMenu(){if(connected())returnRequested_.store(true);else returnReady_.store(true);}
  bool consumeReturnToMenu(){return returnReady_.exchange(false);}
  void noteTrianglePress(){triangleUntil_.store(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count()+750);}
  // Read-only observational counters, not a coherent protocol snapshot.
  uint32_t diagnosticRequests() const{return requests_.load(std::memory_order_relaxed);}
  uint32_t diagnosticCompleted() const{return completed_.load(std::memory_order_relaxed);}
#ifdef TM3ONLINE_TESTING
  void dropNextDatagramsForTest(uint32_t count){testDrops_.store(count,std::memory_order_release);}
  void dropNextRequestsForTest(uint32_t count){testRequestDrops_.store(count,std::memory_order_release);}
  void dropNextResponsesForTest(uint32_t count){testResponseDrops_.store(count,std::memory_order_release);}
  void setNextSequenceForTest(uint32_t sequence){nextSequence_=sequence;}
  uint64_t udpWakeCountForTest() const{return udpWakeCount_.load(std::memory_order_relaxed);}
#endif

private:
#pragma pack(push,1)
  struct MailboxSegment {
    uint32_t address,size;
  };
  struct Mailbox {
    uint32_t magic;
    uint16_t version,status;
    uint16_t command,flags;
    uint32_t sequence,sendSize,recvCapacity,recvSize,callSite;
    uint32_t sendAddress,recvAddress;
    uint32_t sendSegmentCount,recvSegmentCount;
    MailboxSegment sendSegments[4],recvSegments[4];
  };
  struct Control {
    uint32_t magic;
    uint16_t version,kind;
    uint32_t udpPort,reserved;
    uint64_t session;
  };
  struct Wire {
    uint32_t magic;
    uint16_t version,command;
    uint64_t session;
    uint32_t sequence,replyTo,ordinal,payloadSize,expectedSize,callSite,crc;
    uint32_t fragmentOffset,fragmentSize;
  };
#pragma pack(pop)

  struct Incoming {
    uint16_t command{};
    uint32_t sequence{},replyTo{},ordinal{},expectedSize{},callSite{},crc{};
    std::vector<uint8_t> payload;
    std::vector<uint8_t> receivedFragments;
    uint32_t fragmentCount{},receivedCount{};
    bool complete{};
    std::chrono::steady_clock::time_point diagnosticReady{};
  };
  struct RamRange {
    size_t offset{};
    uint32_t size{};
  };
  struct Pending {
    uint16_t command{};
    uint32_t sequence{},replyTo{},ordinal{},expectedSize{},callSite{},retransmissions{};
    std::vector<RamRange> recvRanges;
    std::vector<uint8_t> payload;
    std::chrono::steady_clock::time_point lastSent;
    std::chrono::steady_clock::time_point diagnosticObserved{};
    uint64_t diagnosticObservedQpc{};
    double diagnosticMaxLoopUs{};
  };

  static constexpr uint32_t kMagic=0x4F334D54; // bytes en RAM/red: TM3O
  static constexpr uint16_t kMailboxVersion=5,kProtocolVersion=7;
  static constexpr uint16_t kHello=1,kAccept=2,kRoleReady=3,kRoleAssign=4,kReturnToMenu=5;
  std::atomic<bool> returnRequested_{false},returnReady_{false};
  bool seenLinkedMenu_=false;
  std::atomic<int64_t> triangleUntil_{0};
  static constexpr uint16_t kRoleRequest=1,kTransfer=2,kBatchTransfer=3;
  static constexpr uint16_t kConnectedFlag=0x0100,kExpandedRamFlag=0x0200;
  static constexpr size_t kMailboxOffset=0x47900,kMaxPayload=64*1024,kFragmentPayload=1200;
  static constexpr auto kRetransmitDelay=std::chrono::milliseconds(8);

  SOCKET tcp_=INVALID_SOCKET,listen_=INVALID_SOCKET,udp_=INVALID_SOCKET;
  // Worker initializes this event. Close only after sockets close and worker joins,
  // so shutdown cannot leave Winsock signaling a released/reused event handle.
  WSAEVENT udpReadEvent_=WSA_INVALID_EVENT;
  std::atomic<uint64_t> udpWakeCount_{0};
  sockaddr_in peerUdp_{};
  uint64_t session_{};
  std::jthread worker_;
  std::atomic<bool> connected_{false};
  std::atomic<uint16_t> localRole_{0};
  bool transportHost_{};
  uint32_t localRoleRound_{},remoteRoleRound_{};
  uint64_t roleOrder_{},localRoleOrder_{},remoteRoleOrder_{};
  bool localRoleWaiting_{},remoteRoleWaiting_{};
  uint32_t nextSequence_{};
  std::atomic<uint32_t> requests_{0},udpSent_{0},udpReceived_{0},completed_{0},errors_{0},lastSequence_{0};
  std::atomic<uint32_t> lastSendSize_{0},lastRecvCapacity_{0};
  std::atomic<uint32_t> roleRequests_{0},lastCallSite_{0},lastSendWord_{0},lastRecvWord_{0};
  std::atomic<uint32_t> lastOrdinal_{0},lastRemoteOrdinal_{0},pendingRetransmissions_{0};
#ifdef TM3ONLINE_TESTING
  std::atomic<uint32_t> testDrops_{0},testRequestDrops_{0},testResponseDrops_{0};
#endif
  std::atomic<uint8_t*> ram_{nullptr};
  std::atomic<size_t> ramSize_{0};
  std::atomic<bool> rngInstrumentationReady_{false},rngDumped_{false};
  std::atomic<uint32_t> rngCallCount_{0};
  std::atomic<bool> aiProfileReady_{false};
  std::atomic<uint32_t> aiProfileEventCount_{0},aiProfileHistogramSequence_{0};
  std::atomic<uint64_t> aiProfileDroppedEvents_{0};
  mutable std::mutex mutex_;
  std::unordered_map<uint32_t,Incoming> incomingRequests_;
  std::unordered_map<uint32_t,Incoming> incomingResponses_;
  std::unordered_map<uint32_t,Pending> responseReplay_;
  std::unordered_map<uint32_t,uint32_t> callOrdinals_;
  std::optional<Pending> pending_;
  std::string status_="offline";
  std::ofstream trace_;
  std::ofstream aiProfileCsv_;
  uint32_t aiProfileGeneration_{},aiProfileNextEvent_{},aiProfileLastHistogramSequence_{};
  uint64_t aiProfilePolls_{};
  uint32_t traceEvents_{};
  double diagnosticLoopUs_{};
  void appendWaitTiming(std::ostringstream& line,const Incoming& incoming) const;
  static constexpr uint32_t kTraceLimit=50000,kTraceFlushInterval=64;

  void workerHost(uint16_t port,std::stop_token stop);
  void workerJoin(std::string host,uint16_t port,std::stop_token stop);
  void sessionLoop(std::stop_token stop);
  void processTcpControls();
  void receiveDatagrams();
  void processMailbox();
  bool beginRoleNegotiation();
  void assignRolesIfReady();
  bool openUdp(uint16_t requestedPort,uint16_t& boundPort);
  bool sendPacket(const Pending& packet);
  bool sendAll(const void* data,size_t size);
  bool recvAll(void* data,size_t size);
  void setStatus(std::string value);
  void openTrace(const wchar_t* filename);
  void trace(std::string line);
  void dumpRngCallerRing(const uint8_t* ram,size_t ramSize,uint32_t ordinal,
                         uint32_t localTime,uint32_t localRandom,
                         uint32_t peerTime,uint32_t peerRandom);
  bool initializeAiProfile(uint8_t* ram,size_t ramSize);
  void drainAiProfile(uint8_t* ram,size_t ramSize);
  void dumpAiProfileHistogram(const uint8_t* ram,size_t ramSize,uint32_t sequence);
  void closeSockets();
  static uint16_t readMailboxStatus(const Mailbox* mailbox);
  void writeMailboxStatus(Mailbox* mailbox,uint16_t status);
  static void writeMailboxFlags(Mailbox* mailbox,uint16_t flags);
  static bool translateRamRange(size_t ramSize,uint32_t address,size_t size,size_t& offset);
  static uint32_t crc32(const uint8_t* data,size_t size);
};
