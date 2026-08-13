#pragma once

#include <cstdint>

#ifdef SELECTSPEAK_NATIVE_EXPORTS
#define SS_API extern "C" __declspec(dllexport)
#else
#define SS_API extern "C" __declspec(dllimport)
#endif

inline constexpr std::uint32_t SELECTSPEAK_NATIVE_API_VERSION = 1;

using ss_capture_callback_t = void(__cdecl*)(const wchar_t*, void*);
using ss_activation_callback_t = int(__cdecl*)(void*);
using ss_record_callback_t =
    void(__cdecl*)(unsigned int, unsigned int, unsigned int, void*);
using ss_ocr_callback_t =
    void(__cdecl*)(const wchar_t*, unsigned int, void*);
using ss_audio_callback_t = void (*)(const std::uint8_t*, std::uint32_t, void*);
using ss_word_callback_t = void (*)(std::uint64_t, std::uint32_t,
                                    std::uint32_t, void*);
using ss_finished_callback_t = void (*)(int, void*);
using ss_voice_callback_t = void (*)(const wchar_t*, const char*, const char*,
                                     const char*, void*);

SS_API std::uint32_t ss_api_version();
SS_API void ss_shutdown();

SS_API int ss_input_start(unsigned int modifiers, unsigned int virtual_key,
                          ss_capture_callback_t callback,
                          ss_activation_callback_t activation_callback,
                          void* context);
SS_API int ss_input_rebind(unsigned int modifiers, unsigned int virtual_key);
SS_API int ss_input_capture_now();
SS_API int ss_input_record_start(ss_record_callback_t callback, void* context);
SS_API void ss_input_record_stop();
SS_API void ss_input_stop();
SS_API unsigned int ss_input_last_capture_source();
SS_API unsigned long long ss_input_last_activation_time_ms();
SS_API unsigned int ss_input_last_error(char* buffer, unsigned int length);

SS_API int ss_ocr_start(unsigned int modifiers, unsigned int virtual_key,
                        const wchar_t* language, ss_ocr_callback_t callback,
                        void* context);
SS_API void ss_ocr_cancel();
SS_API int ss_ocr_is_active();
SS_API void ss_ocr_stop();
SS_API unsigned int ss_ocr_last_error(char* buffer, unsigned int length);
SS_API int ss_ocr_recognize_bgra(const unsigned char* pixels,
                                 unsigned int width, unsigned int height,
                                 unsigned int stride, const wchar_t* language,
                                 ss_ocr_callback_t callback, void* context);

SS_API std::uint32_t ss_voice_list(ss_voice_callback_t callback, void* context);
SS_API int ss_voice_initialize(const wchar_t* voice_path,
                               const char* credential);
SS_API void ss_voice_set_audio_callback(ss_audio_callback_t callback,
                                        void* context);
SS_API void ss_voice_set_word_callback(ss_word_callback_t callback,
                                       void* context);
SS_API void ss_voice_set_finished_callback(ss_finished_callback_t callback,
                                           void* context);
SS_API int ss_voice_speak(const wchar_t* text);
SS_API int ss_voice_stop();
SS_API void ss_voice_shutdown();
SS_API std::uint32_t ss_voice_last_error(char* buffer,
                                         std::uint32_t capacity);
