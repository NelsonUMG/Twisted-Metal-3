#pragma once
#include <cstddef>
#include <cstdint>

extern "C" {
typedef bool (*retro_environment_t)(unsigned, void*);
typedef void (*retro_video_refresh_t)(const void*, unsigned, unsigned, size_t);
typedef void (*retro_audio_sample_t)(int16_t, int16_t);
typedef size_t (*retro_audio_sample_batch_t)(const int16_t*, size_t);
typedef void (*retro_input_poll_t)(void);
typedef int16_t (*retro_input_state_t)(unsigned, unsigned, unsigned, unsigned);

struct retro_game_info { const char* path; const void* data; size_t size; const char* meta; };
struct retro_system_info { const char* library_name; const char* library_version; const char* valid_extensions; bool need_fullpath; bool block_extract; };
struct retro_game_geometry { unsigned base_width, base_height, max_width, max_height; float aspect_ratio; };
struct retro_system_timing { double fps, sample_rate; };
struct retro_system_av_info { retro_game_geometry geometry; retro_system_timing timing; };
struct retro_variable { const char* key; const char* value; };
struct retro_log_callback { void (*log)(int level, const char* fmt, ...); };
}

enum : unsigned {
  RETRO_API_VERSION = 1,
  RETRO_ENVIRONMENT_GET_CAN_DUPE = 3,
  RETRO_ENVIRONMENT_SET_MESSAGE = 6,
  RETRO_ENVIRONMENT_SHUTDOWN = 7,
  RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL = 8,
  RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY = 9,
  RETRO_ENVIRONMENT_SET_PIXEL_FORMAT = 10,
  RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS = 11,
  RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE = 13,
  RETRO_ENVIRONMENT_SET_HW_RENDER = 14,
  RETRO_ENVIRONMENT_GET_VARIABLE = 15,
  RETRO_ENVIRONMENT_SET_VARIABLES = 16,
  RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE = 17,
  RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME = 18,
  RETRO_ENVIRONMENT_GET_LOG_INTERFACE = 27,
  RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY = 30,
  RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY = 31,
  RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO = 32,
  RETRO_ENVIRONMENT_SET_CONTROLLER_INFO = 35,
  RETRO_ENVIRONMENT_SET_MEMORY_MAPS = 36,
  RETRO_ENVIRONMENT_SET_GEOMETRY = 37,
  RETRO_ENVIRONMENT_GET_USERNAME = 38,
  RETRO_ENVIRONMENT_GET_LANGUAGE = 39,
  RETRO_ENVIRONMENT_GET_INPUT_BITMASKS = 51,
};

enum retro_pixel_format : unsigned { RETRO_PIXEL_FORMAT_0RGB1555=0, RETRO_PIXEL_FORMAT_XRGB8888=1, RETRO_PIXEL_FORMAT_RGB565=2 };
enum : unsigned { RETRO_DEVICE_NONE=0, RETRO_DEVICE_JOYPAD=1, RETRO_MEMORY_SYSTEM_RAM=2 };
enum : unsigned {
  RETRO_DEVICE_ID_JOYPAD_B=0, RETRO_DEVICE_ID_JOYPAD_Y=1, RETRO_DEVICE_ID_JOYPAD_SELECT=2,
  RETRO_DEVICE_ID_JOYPAD_START=3, RETRO_DEVICE_ID_JOYPAD_UP=4, RETRO_DEVICE_ID_JOYPAD_DOWN=5,
  RETRO_DEVICE_ID_JOYPAD_LEFT=6, RETRO_DEVICE_ID_JOYPAD_RIGHT=7, RETRO_DEVICE_ID_JOYPAD_A=8,
  RETRO_DEVICE_ID_JOYPAD_X=9, RETRO_DEVICE_ID_JOYPAD_L=10, RETRO_DEVICE_ID_JOYPAD_R=11,
  RETRO_DEVICE_ID_JOYPAD_L2=12, RETRO_DEVICE_ID_JOYPAD_R2=13, RETRO_DEVICE_ID_JOYPAD_L3=14,
  RETRO_DEVICE_ID_JOYPAD_R3=15, RETRO_DEVICE_ID_JOYPAD_MASK=256
};
