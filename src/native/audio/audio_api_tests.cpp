#include "../api.h"

#include <cstdint>
#include <iostream>
#include <type_traits>

namespace {

int failures = 0;
int callbacks = 0;

void Expect(const bool condition, const char* const message)
{
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

void __cdecl OnAudioEvent(const ss_audio_event_t*, void*)
{
    ++callbacks;
}

}  // namespace

int main()
{
    static_assert(SELECTSPEAK_NATIVE_API_VERSION == 7);
    static_assert(std::is_standard_layout_v<ss_audio_format_t>);
    static_assert(std::is_standard_layout_v<ss_audio_boundary_t>);
    static_assert(std::is_standard_layout_v<ss_audio_submit_result_t>);
    static_assert(std::is_standard_layout_v<ss_audio_event_t>);
    static_assert(sizeof(ss_audio_format_t) == 16);
    static_assert(sizeof(ss_audio_boundary_t) == 16);
    static_assert(sizeof(ss_audio_submit_result_t) == 24);
    static_assert(sizeof(ss_audio_event_t) == 48);
    static_assert(sizeof(ss_natural_synthesis_result_t) == 32);

    ss_audio_format_t format{sizeof(ss_audio_format_t), 24'000, 1,
                             SS_SAMPLE_FORMAT_PCM_S16_LE};
    ss_audio_request_handle_t handle = 99;
    Expect(ss_audio_request_create(0, &format, 10, OnAudioEvent, nullptr,
                                   &handle) == SS_STATUS_INVALID_REQUEST,
           "request zero is invalid");
    Expect(handle == SS_INVALID_AUDIO_REQUEST_HANDLE,
           "rejected create clears its output handle");

    Expect(ss_audio_request_create(1, &format, 10, OnAudioEvent, nullptr,
                                   &handle) == SS_STATUS_DEVICE_ERROR,
           "Package F stub rejects valid requests without accepting them");
    Expect(handle == SS_INVALID_AUDIO_REQUEST_HANDLE,
           "stub create never exposes a handle");
    Expect(callbacks == 0, "rejected create emits no lifecycle callback");

    ss_audio_submit_result_t result{sizeof(ss_audio_submit_result_t), 0, 7, 9};
    Expect(ss_audio_request_submit(handle, nullptr, 0, nullptr, 0, &result) ==
               SS_STATUS_INVALID_HANDLE,
           "operations reject invalid handles");
    Expect(result.accepted_frames == 0 &&
               result.buffered_frames_after_submit == 0,
           "failed submit accepts no PCM or telemetry");
    Expect(ss_audio_request_destroy(handle) == SS_STATUS_INVALID_HANDLE,
           "destroyed or unknown handles remain invalid");

    if (failures == 0) {
        std::cout << "audio ABI checks passed\n";
    }
    return failures == 0 ? 0 : 1;
}
