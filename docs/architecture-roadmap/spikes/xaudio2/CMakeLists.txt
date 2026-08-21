# Package C XAudio2 feasibility check - NON-PRODUCTION.
#
# Deliberately a standalone project, not part of src/native, so this evidence
# code can never be linked into the shipped selectspeak_native DLL.

cmake_minimum_required(VERSION 3.20)
project(selectspeak_xaudio2_spike LANGUAGES CXX)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "The XAudio2 spike requires 64-bit Windows")
endif()

add_executable(xaudio2_spike xaudio2_spike.cpp)
target_compile_features(xaudio2_spike PRIVATE cxx_std_17)
target_compile_definitions(xaudio2_spike PRIVATE
    WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)

if(MSVC)
    target_compile_options(xaudio2_spike PRIVATE
        /utf-8 /W4 /permissive- /Zc:__cplusplus)
endif()

# XAudio2 2.9 ships with Windows 10/11; only an import library is needed.
target_link_libraries(xaudio2_spike PRIVATE xaudio2 ole32)
