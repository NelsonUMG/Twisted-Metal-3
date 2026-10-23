#pragma once
#include "core_host.hpp"
#include <commctrl.h>
#include <filesystem>
#include <vector>
#include <memory>
#include <functional>

class ConsoleUI {
public:
  explicit ConsoleUI(CoreHost& core):core_(core){}
  void attach(HWND window,const std::filesystem::path& base,const std::filesystem::path& game,const std::filesystem::path& engine,bool linked);
  bool handle(HWND,UINT,WPARAM,LPARAM);
  bool showStatistics() const{return stats_;}
  bool paused() const{return paused_.load();}
  void openSettings(int page);
  static std::wstring menuCaption(HMENU menu,int index);
  static std::wstring windowCaption(bool linked,bool statistics,double fps);
  bool translate(MSG& message);
  void pollPadCapture(uint32_t mask);
  uint32_t capturePadMask() const;
  void setGameAction(std::function<void(const std::filesystem::path&)> action){gameAction_=std::move(action);}
  void contentChanged(const std::filesystem::path& game,bool linked);
  void paintHome(HDC,const RECT&);
  bool english() const{return language_==0;}
  std::wstring caption(double fps) const;
private:
  struct MenuLabel {std::wstring text;bool bar=false;int id=0;bool separator=false;};
  CoreHost& core_;
  HWND window_{},settings_{},categories_{},help_{},pageTitle_{};
  HFONT font_{},iconFont_{};
  std::filesystem::path base_,game_,engine_,ini_;
  std::vector<HWND> controls_;
  std::vector<int> navigation_;
  std::vector<std::unique_ptr<MenuLabel>> menuLabels_;
  HBRUSH background_=CreateSolidBrush(RGB(22,29,41)),surface_=CreateSolidBrush(RGB(31,42,59));
  int page_=0,aspect_=0,volume_=100;
  int resolution_=1,controllerIndex_=-1,audioDevice_=-1;
  int editingPort_=0,controllerIndex2_=-1;
  bool secondController_=false;
  std::array<int,16> keys2_{},pads2_{};
  int language_=0,latency_=80,deinterlace_=0,overscan_=0;
  bool cdAudio_=true;
  std::filesystem::path bios_;
  std::function<void(const std::filesystem::path&)> gameAction_;
  bool pgxp_=false,widescreen_=false;
  int captureId_=0;
  uint32_t previousPad_=0;
  ULONGLONG captureDeadline_=0;
  std::array<int,16> pads_{};
  bool linked_=false,smooth_=false,muted_=false,stats_=false,controller_=true,fullscreen_=false;
  bool confirmClose_=false,doubleClick_=true,controllerWindow_=false,propertiesWindow_=false,startFullscreen_=false;
  bool rebuilding_=false;
  int captureKey_=VK_F10,fullscreenKey_=VK_F11,exitKey_=VK_ESCAPE;
  std::atomic<bool> paused_{false};
  RECT restored_{};
  std::array<int,16> keys_{};
  std::array<int,16>& editingKeys(){return editingPort_?keys2_:keys_;}
  std::array<int,16>& editingPads(){return editingPort_?pads2_:pads_;}
  HWND make(const wchar_t*,const wchar_t*,DWORD,int,int,int,int,int);
  void page();void apply();void save();void syncMenu();void updateCore();void fullscreen();void capture();void folder(const std::filesystem::path&);
  void navigation();void item(HMENU,int,const wchar_t*,UINT=MF_STRING,bool=false);bool draw(UINT,LPARAM);void defaults();
  void separator(HMENU);
  void buildMenu();void openGame();void selectBios();void refreshLanguage();
  const wchar_t* tr(const wchar_t* en,const wchar_t* es) const{return english()?en:es;}
  void beginBinding(int id);void finishBinding(int value,bool cancel=false);void bindingLabels();
  static LRESULT CALLBACK settingsProc(HWND,UINT,WPARAM,LPARAM);
};
