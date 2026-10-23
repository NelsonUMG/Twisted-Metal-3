cmake_minimum_required(VERSION 3.24)
project(TM3Online LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
  # Distribucion portable: evita depender del VC++ Redistributable en la otra PC.
  set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
add_executable(TM3Online WIN32
  src/main.cpp
  src/core_host.cpp
  src/audio_waveout.cpp
  src/net_bridge.cpp
)
target_include_directories(TM3Online PRIVATE include)
target_compile_definitions(TM3Online PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(TM3Online PRIVATE winmm ws2_32 xinput9_1_0 shell32)
if(MSVC)
  target_compile_options(TM3Online PRIVATE /W4 /permissive- /EHsc)
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(TM3NetSmokeTest
    tests/net_bridge_smoketest.cpp
    src/net_bridge.cpp
  )
  target_include_directories(TM3NetSmokeTest PRIVATE include)
  target_compile_definitions(TM3NetSmokeTest PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX TM3ONLINE_TESTING)
  target_link_libraries(TM3NetSmokeTest PRIVATE ws2_32)
  if(MSVC)
    target_compile_options(TM3NetSmokeTest PRIVATE /W4 /permissive- /EHsc)
  endif()
  add_test(NAME TM3NetSmokeTest COMMAND TM3NetSmokeTest)
endif()
