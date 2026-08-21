cmake_minimum_required(VERSION 3.20)
project(selectspeak_native LANGUAGES CXX RC)

include(CTest)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "SelectSpeak's native bridge requires 64-bit Windows")
endif()

option(SELECTSPEAK_ENABLE_NATURAL_VOICE
    "Build Microsoft Natural Voice support into the native bridge" ON)
option(SELECTSPEAK_ENABLE_ASAN
    "Build the native bridge with AddressSanitizer" OFF)
set(SELECTSPEAK_VERSION "0.1.3" CACHE STRING
    "SelectSpeak product version embedded in the native bridge")
if(NOT SELECTSPEAK_VERSION MATCHES "^[0-9]+\.[0-9]+\.[0-9]+$")
    message(FATAL_ERROR "SELECTSPEAK_VERSION must use major.minor.patch")
endif()
string(REPLACE "." "," SELECTSPEAK_VERSION_COMMAS "${SELECTSPEAK_VERSION}")
configure_file(version.rc.in selectspeak_version.rc @ONLY)

set(SELECTSPEAK_NATIVE_SOURCES
    api.cpp
    audio/audio_api_stub.cpp
    input/input_bridge.cpp
    input/hotkeys/hotkey_runtime.cpp
    input/ocr/ocr_capture.cpp
    input/ocr/ocr_layout.cpp
    input/selection/selection_capture.cpp
    input/selection/selection_policy.cpp)
list(APPEND SELECTSPEAK_NATIVE_SOURCES
    "${CMAKE_CURRENT_BINARY_DIR}/selectspeak_version.rc")

if(SELECTSPEAK_ENABLE_NATURAL_VOICE)
    set(SPEECHSDK_ROOT "" CACHE PATH
        "Root of the Microsoft.CognitiveServices.Speech NuGet package")
    if(NOT SPEECHSDK_ROOT)
        message(FATAL_ERROR
            "SPEECHSDK_ROOT is required when Natural Voice support is enabled")
    endif()
    list(APPEND SELECTSPEAK_NATIVE_SOURCES
        natural_voice/natural_voice.cpp
        natural_voice/speech_runtime_config.cpp)
else()
    list(APPEND SELECTSPEAK_NATIVE_SOURCES
        natural_voice/natural_voice_stub.cpp)
endif()

add_library(selectspeak_native SHARED ${SELECTSPEAK_NATIVE_SOURCES})
target_compile_features(selectspeak_native PRIVATE cxx_std_17)
target_compile_definitions(selectspeak_native PRIVATE
    SELECTSPEAK_NATIVE_EXPORTS WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
if(MSVC)
    target_compile_options(selectspeak_native PRIVATE
        /utf-8 /W4 /permissive- /sdl /Zc:__cplusplus /guard:cf)
    target_link_options(selectspeak_native PRIVATE /guard:cf /CETCOMPAT)
    if(SELECTSPEAK_ENABLE_ASAN)
        target_compile_options(selectspeak_native PRIVATE /fsanitize=address)
        target_link_options(selectspeak_native PRIVATE /INCREMENTAL:NO)
    endif()
    if(SELECTSPEAK_ENABLE_NATURAL_VOICE AND MSVC_VERSION LESS 1930)
        target_compile_options(selectspeak_native PRIVATE /await)
    endif()
endif()
target_link_libraries(selectspeak_native PRIVATE
    gdi32 msimg32 ole32 shcore uiautomationcore user32 windowsapp)
set_target_properties(selectspeak_native PROPERTIES OUTPUT_NAME "selectspeak_native")

if(SELECTSPEAK_ENABLE_NATURAL_VOICE)
    target_include_directories(selectspeak_native PRIVATE
        "${SPEECHSDK_ROOT}/build/native/include/cxx_api"
        "${SPEECHSDK_ROOT}/build/native/include/c_api")
    target_link_libraries(selectspeak_native PRIVATE
        "${SPEECHSDK_ROOT}/build/native/x64/Release/Microsoft.CognitiveServices.Speech.core.lib")
endif()

if(BUILD_TESTING)
    add_executable(selectspeak_audio_api_tests
        audio/audio_api_stub.cpp
        audio/audio_api_tests.cpp)
    target_compile_features(selectspeak_audio_api_tests PRIVATE cxx_std_17)
    target_compile_definitions(selectspeak_audio_api_tests PRIVATE
        SELECTSPEAK_NATIVE_EXPORTS)
    if(MSVC)
        target_compile_options(selectspeak_audio_api_tests PRIVATE
            /utf-8 /W4 /permissive- /sdl /Zc:__cplusplus)
    endif()
    add_test(NAME audio_api COMMAND selectspeak_audio_api_tests)

    add_executable(selectspeak_ocr_layout_tests
        input/ocr/ocr_layout.cpp
        input/ocr/ocr_layout_tests.cpp)
    target_compile_features(selectspeak_ocr_layout_tests PRIVATE cxx_std_17)
    target_compile_definitions(selectspeak_ocr_layout_tests PRIVATE NOMINMAX)
    if(MSVC)
        target_compile_options(selectspeak_ocr_layout_tests PRIVATE
            /utf-8 /W4 /permissive- /sdl /Zc:__cplusplus)
    endif()
    add_test(NAME ocr_layout COMMAND selectspeak_ocr_layout_tests)

    add_executable(selectspeak_selection_policy_tests
        input/selection/selection_policy.cpp
        input/selection/selection_policy_tests.cpp)
    target_compile_features(selectspeak_selection_policy_tests PRIVATE cxx_std_17)
    if(MSVC)
        target_compile_options(selectspeak_selection_policy_tests PRIVATE
            /utf-8 /W4 /permissive- /sdl /Zc:__cplusplus)
    endif()
    add_test(NAME selection_policy COMMAND selectspeak_selection_policy_tests)

    add_executable(selectspeak_clipboard_snapshot_tests
        input/selection/clipboard_snapshot_tests.cpp)
    target_compile_features(selectspeak_clipboard_snapshot_tests PRIVATE cxx_std_17)
    target_compile_definitions(selectspeak_clipboard_snapshot_tests PRIVATE
        WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(selectspeak_clipboard_snapshot_tests PRIVATE ole32 oleaut32)
    if(MSVC)
        target_compile_options(selectspeak_clipboard_snapshot_tests PRIVATE
            /utf-8 /W4 /permissive- /sdl /Zc:__cplusplus)
    endif()
    add_test(NAME clipboard_snapshot COMMAND selectspeak_clipboard_snapshot_tests)

    if(SELECTSPEAK_ENABLE_NATURAL_VOICE)
        add_executable(selectspeak_speech_runtime_config_tests
            natural_voice/speech_runtime_config.cpp
            natural_voice/speech_runtime_config_tests.cpp)
        target_compile_features(selectspeak_speech_runtime_config_tests PRIVATE
            cxx_std_17)
        target_compile_definitions(selectspeak_speech_runtime_config_tests PRIVATE
            WIN32_LEAN_AND_MEAN NOMINMAX)
        if(MSVC)
            target_compile_options(selectspeak_speech_runtime_config_tests PRIVATE
                /utf-8 /W4 /permissive- /sdl /Zc:__cplusplus)
        endif()
        add_test(NAME natural_voice_speech_runtime_config
            COMMAND selectspeak_speech_runtime_config_tests)
    endif()
endif()
