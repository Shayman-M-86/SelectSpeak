#pragma once

#include <cstdint>

#ifdef SELECTSPEAK_NATIVE_EXPORTS
#define SS_API extern "C" __declspec(dllexport)
#else
#define SS_API extern "C" __declspec(dllimport)
#endif

inline constexpr std::uint32_t SELECTSPEAK_NATIVE_API_VERSION = 7;

enum ss_status_t : std::uint32_t {
    SS_STATUS_OK = 0,
    SS_STATUS_INVALID_HANDLE = 1,
    SS_STATUS_INVALID_REQUEST = 2,
    SS_STATUS_INVALID_ARGUMENT = 3,
    SS_STATUS_INVALID_BOUNDARY = 4,
    SS_STATUS_WRONG_STATE = 5,
    SS_STATUS_DEVICE_ERROR = 6,
    SS_STATUS_CLOSED = 7,
    SS_STATUS_INTERNAL_ERROR = 8,
};

enum ss_sample_format_t : std::uint32_t {
    SS_SAMPLE_FORMAT_PCM_S16_LE = 1,
};

enum ss_audio_event_kind_t : std::uint32_t {
    SS_AUDIO_EVENT_STARTED = 1,
    SS_AUDIO_EVENT_PLAYED_WORD = 2,
    SS_AUDIO_EVENT_UNDERRUN = 3,
    SS_AUDIO_EVENT_TERMINAL = 4,
};

enum ss_terminal_status_t : std::uint32_t {
    SS_TERMINAL_NONE = 0,
    SS_TERMINAL_COMPLETED = 1,
    SS_TERMINAL_CANCELLED = 2,
    SS_TERMINAL_SUPERSEDED = 3,
    SS_TERMINAL_FAILED = 4,
    SS_TERMINAL_CLOSED = 5,
};

using ss_audio_request_handle_t = std::uint64_t;
inline constexpr ss_audio_request_handle_t SS_INVALID_AUDIO_REQUEST_HANDLE = 0;

struct ss_audio_format_t {
    std::uint32_t size;
    std::uint32_t sample_rate_hz;
    std::uint32_t channel_count;
    std::uint32_t sample_format;
};

struct ss_audio_boundary_t {
    std::uint64_t frame_offset;
    std::uint32_t text_position;
    std::uint32_t text_length;
};

struct ss_audio_submit_result_t {
    std::uint32_t size;
    std::uint32_t reserved;
    std::uint64_t accepted_frames;
    std::uint64_t buffered_frames_after_submit;
};

struct ss_audio_event_t {
    std::uint32_t size;
    std::uint32_t kind;
    std::uint64_t request_id;
    std::uint32_t terminal_status;
    std::uint32_t status;
    std::uint32_t text_position;
    std::uint32_t text_length;
    std::uint64_t buffered_frames;
    const char* diagnostic;
};

struct ss_natural_synthesis_result_t {
    std::uint32_t size;
    std::uint32_t status;
    std::uint64_t generated_frames;
    std::uint64_t synthesis_duration_us;
    std::uint64_t buffered_frames_after_submit;
};

using ss_capture_callback_t = void(__cdecl*)(const wchar_t*, void*);
using ss_activation_callback_t = int(__cdecl*)(void*);
using ss_ocr_callback_t =
    void(__cdecl*)(const wchar_t*, unsigned int, void*);
using ss_audio_callback_t =
    void(__cdecl*)(const std::uint8_t*, std::uint32_t, void*);
using ss_word_callback_t = void(__cdecl*)(std::uint64_t, std::uint32_t,
                                          std::uint32_t, void*);
using ss_voice_callback_t = void(__cdecl*)(const wchar_t*, const char*,
                                           const char*, const char*, void*);
using ss_audio_event_callback_t =
    void(__cdecl*)(const ss_audio_event_t*, void*);

SS_API std::uint32_t ss_api_version();
SS_API void ss_shutdown();

SS_API int ss_input_start(unsigned int modifiers, unsigned int virtual_key,
                          ss_capture_callback_t callback,
                          ss_activation_callback_t activation_callback,
                          void* context);
SS_API int ss_input_rebind(unsigned int modifiers, unsigned int virtual_key);
SS_API int ss_input_capture_now();
SS_API void ss_input_stop();
SS_API unsigned int ss_input_last_capture_source();
SS_API unsigned long long ss_input_last_activation_time_ms();
SS_API unsigned int ss_input_last_capture_trace(char* buffer,
                                                 unsigned int length);
SS_API unsigned int ss_input_last_error(char* buffer, unsigned int length);

SS_API int ss_ocr_start(unsigned int modifiers, unsigned int virtual_key,
                        const wchar_t* language, ss_ocr_callback_t callback,
                        void* context);
SS_API void ss_ocr_cancel();
SS_API int ss_ocr_is_active();
SS_API void ss_ocr_stop();
SS_API unsigned int ss_ocr_last_error(char* buffer, unsigned int length);
SS_API int ss_ocr_recognize_bgra(const unsigned char* pixels,
                                 std::uint64_t buffer_length,
                                 unsigned int width, unsigned int height,
                                 unsigned int stride, const wchar_t* language,
                                 ss_ocr_callback_t callback, void* context);

SS_API std::uint32_t ss_voice_list(ss_voice_callback_t callback, void* context);
SS_API int ss_voice_initialize(const wchar_t* voice_path,
                               const char* voice_name);
SS_API void ss_voice_set_audio_callback(ss_audio_callback_t callback,
                                        void* context);
SS_API void ss_voice_set_word_callback(ss_word_callback_t callback,
                                       void* context);
SS_API int ss_voice_speak(const wchar_t* text);
SS_API int ss_voice_stop();
SS_API void ss_voice_shutdown();
SS_API std::uint32_t ss_voice_last_error(char* buffer,
                                         std::uint32_t capacity);

SS_API std::uint32_t ss_audio_request_create(
    std::uint64_t request_id, const ss_audio_format_t* format,
    std::uint32_t request_text_length_utf16,
    ss_audio_event_callback_t callback, void* context,
    ss_audio_request_handle_t* handle);
SS_API std::uint32_t ss_audio_request_submit(
    ss_audio_request_handle_t handle, const void* pcm,
    std::uint64_t pcm_byte_length, const ss_audio_boundary_t* boundaries,
    std::uint32_t boundary_count, ss_audio_submit_result_t* result);
SS_API std::uint32_t ss_audio_request_finish_input(
    ss_audio_request_handle_t handle);
SS_API std::uint32_t ss_audio_request_pause(ss_audio_request_handle_t handle);
SS_API std::uint32_t ss_audio_request_resume(ss_audio_request_handle_t handle);
SS_API std::uint32_t ss_audio_request_stop(ss_audio_request_handle_t handle,
                                           std::uint32_t terminal_reason);
SS_API std::uint32_t ss_audio_request_destroy(ss_audio_request_handle_t handle);
