cmake_minimum_required(VERSION 3.20)
project(selectspeak_natural_voice LANGUAGES CXX)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "SelectSpeak's Natural Voice bridge requires 64-bit Windows")
endif()

set(SPEECHSDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/packages/Microsoft.CognitiveServices.Speech.1.41.1"
    CACHE PATH "Root of the Microsoft.CognitiveServices.Speech NuGet package")

add_library(selectspeak_natural_voice SHARED
    natural_voice.cpp
    credential_provider.cpp
)
target_compile_features(selectspeak_natural_voice PRIVATE cxx_std_17)
target_compile_definitions(selectspeak_natural_voice PRIVATE
    NATURAL_VOICE_EXPORTS WIN32_LEAN_AND_MEAN NOMINMAX)
if(MSVC AND MSVC_VERSION LESS 1930)
    # C++/WinRT in the VS 2019 Windows SDK still includes the pre-C++20
    # coroutine compatibility header and requires this switch.
    target_compile_options(selectspeak_natural_voice PRIVATE /await)
endif()
target_include_directories(selectspeak_natural_voice PRIVATE
    "${SPEECHSDK_ROOT}/build/native/include/cxx_api"
    "${SPEECHSDK_ROOT}/build/native/include/c_api")
target_link_libraries(selectspeak_natural_voice PRIVATE
    "${SPEECHSDK_ROOT}/build/native/x64/Release/Microsoft.CognitiveServices.Speech.core.lib"
    windowsapp)
set_target_properties(selectspeak_natural_voice PROPERTIES
    OUTPUT_NAME "selectspeak_natural_voice")

add_custom_command(TARGET selectspeak_natural_voice POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${SPEECHSDK_ROOT}/runtimes/win-x64/native"
        "$<TARGET_FILE_DIR:selectspeak_natural_voice>"
    COMMENT "Copying the Microsoft Speech SDK runtime")
