cmake_minimum_required(VERSION 3.20)
project(selectspeak_input LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "SelectSpeak's input bridge requires Windows")
endif()

add_library(selectspeak_input SHARED input_bridge.cpp ocr_capture.cpp)
target_compile_features(selectspeak_input PRIVATE cxx_std_17)
target_compile_definitions(selectspeak_input PRIVATE
    SELECTSPEAK_INPUT_EXPORTS WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
target_link_libraries(selectspeak_input PRIVATE
    gdi32 msimg32 ole32 shcore shell32 uiautomationcore user32 windowsapp)
set_target_properties(selectspeak_input PROPERTIES OUTPUT_NAME "selectspeak_input")
