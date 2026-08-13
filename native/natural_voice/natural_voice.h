#pragma once

#include <cstdint>

#ifdef NATURAL_VOICE_EXPORTS
#define NV_API __declspec(dllexport)
#else
#define NV_API __declspec(dllimport)
#endif

extern "C" {

using nv_audio_callback_t = void (*)(const std::uint8_t* data,
                                      std::uint32_t length,
                                      void* context);
using nv_word_callback_t = void (*)(std::uint64_t audio_offset_ticks,
                                     std::uint32_t text_offset,
                                     std::uint32_t word_length,
                                     void* context);
using nv_finished_callback_t = void (*)(int status, void* context);
using nv_voice_callback_t = void (*)(const wchar_t* package_path,
                                      const char* voice_name,
                                      const char* locale,
                                      const char* display_name,
                                      void* context);

// Enumerates MicrosoftWindows.Voice.* packages and returns the number of voices.
NV_API std::uint32_t nv_list_voices(nv_voice_callback_t callback, void* context);

// A null/empty credential tries the installed Windows runtime credential, then
// the isolated legacy Narrator credential for older package compatibility.
NV_API int nv_initialize(const wchar_t* voice_path, const char* credential);
NV_API void nv_set_audio_callback(nv_audio_callback_t callback, void* context);
NV_API void nv_set_word_callback(nv_word_callback_t callback, void* context);
NV_API void nv_set_finished_callback(nv_finished_callback_t callback, void* context);

// Blocks until synthesis completes. Audio is 24 kHz, signed 16-bit, mono PCM.
NV_API int nv_speak(const wchar_t* text);
NV_API int nv_stop();
NV_API void nv_shutdown();

// Copies a UTF-8 diagnostic into buffer and returns the required size including NUL.
NV_API std::uint32_t nv_last_error(char* buffer, std::uint32_t capacity);

}
