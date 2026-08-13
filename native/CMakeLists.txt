cmake_minimum_required(VERSION 3.20)
project(selectspeak_native LANGUAGES CXX)

include(CTest)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "SelectSpeak's native bridge requires 64-bit Windows")
endif()

option(SELECTSPEAK_ENABLE_NATURAL_VOICE
    "Build Microsoft Natural Voice support into the native bridge" ON)

set(SELECTSPEAK_NATIVE_SOURCES
    api.cpp
    input/input_bridge.cpp
    input/ocr_capture.cpp
    input/ocr_layout.cpp)

if(SELECTSPEAK_ENABLE_NATURAL_VOICE)
    set(SPEECHSDK_ROOT "" CACHE PATH
        "Root of the Microsoft.CognitiveServices.Speech NuGet package")
    if(NOT SPEECHSDK_ROOT)
        message(FATAL_ERROR
            "SPEECHSDK_ROOT is required when Natural Voice support is enabled")
    endif()
    list(APPEND SELECTSPEAK_NATIVE_SOURCES
        natural_voice/natural_voice.cpp
        natural_voice/credential_provider.cpp)
else()
    list(APPEND SELECTSPEAK_NATIVE_SOURCES
        natural_voice/natural_voice_stub.cpp)
endif()

add_library(selectspeak_native SHARED ${SELECTSPEAK_NATIVE_SOURCES})
target_compile_features(selectspeak_native PRIVATE cxx_std_17)
target_compile_definitions(selectspeak_native PRIVATE
    SELECTSPEAK_NATIVE_EXPORTS WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
if(MSVC)
    target_compile_options(selectspeak_native PRIVATE /utf-8)
    if(SELECTSPEAK_ENABLE_NATURAL_VOICE AND MSVC_VERSION LESS 1930)
        target_compile_options(selectspeak_native PRIVATE /await)
    endif()
endif()
target_link_libraries(selectspeak_native PRIVATE
    gdi32 msimg32 ole32 shcore shell32 uiautomationcore user32 windowsapp)
set_target_properties(selectspeak_native PROPERTIES OUTPUT_NAME "selectspeak_native")

if(SELECTSPEAK_ENABLE_NATURAL_VOICE)
    target_include_directories(selectspeak_native PRIVATE
        "${SPEECHSDK_ROOT}/build/native/include/cxx_api"
        "${SPEECHSDK_ROOT}/build/native/include/c_api")
    target_link_libraries(selectspeak_native PRIVATE
        "${SPEECHSDK_ROOT}/build/native/x64/Release/Microsoft.CognitiveServices.Speech.core.lib")
    add_custom_command(TARGET selectspeak_native POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${SPEECHSDK_ROOT}/runtimes/win-x64/native"
            "$<TARGET_FILE_DIR:selectspeak_native>"
        COMMENT "Copying the Microsoft Speech SDK runtime")
endif()

if(BUILD_TESTING)
    add_executable(selectspeak_ocr_layout_tests
        input/ocr_layout.cpp
        input/ocr_layout_tests.cpp)
    target_compile_features(selectspeak_ocr_layout_tests PRIVATE cxx_std_17)
    target_compile_definitions(selectspeak_ocr_layout_tests PRIVATE NOMINMAX)
    if(MSVC)
        target_compile_options(selectspeak_ocr_layout_tests PRIVATE /utf-8)
    endif()
    add_test(NAME ocr_layout COMMAND selectspeak_ocr_layout_tests)

    if(SELECTSPEAK_ENABLE_NATURAL_VOICE)
        add_executable(selectspeak_credential_provider_tests
            natural_voice/credential_provider.cpp
            natural_voice/credential_provider_tests.cpp)
        target_compile_features(selectspeak_credential_provider_tests PRIVATE
            cxx_std_17)
        target_compile_definitions(selectspeak_credential_provider_tests PRIVATE
            WIN32_LEAN_AND_MEAN NOMINMAX)
        add_test(NAME natural_voice_credential_provider
            COMMAND selectspeak_credential_provider_tests)
    endif()
endif()
