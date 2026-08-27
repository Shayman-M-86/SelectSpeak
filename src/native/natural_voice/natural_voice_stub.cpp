#include "../api.h"
#include "../abi_guard.h"

#include <algorithm>
#include <cstring>
#include <string>

namespace {
const std::string unavailable =
    "Natural Voice support was omitted from this SelectSpeak native build";
}

std::uint32_t ss_voice_list(ss_voice_callback_t, void*) { return 0; }

int ss_voice_initialize(const wchar_t*, const char*) { return 1; }

void ss_voice_set_audio_callback(ss_audio_callback_t, void*) {}

void ss_voice_set_word_callback(ss_word_callback_t, void*) {}

int ss_voice_speak(const wchar_t*) { return 1; }

std::uint32_t ss_voice_set_volume(const std::uint32_t volume_percent)
{
    return volume_percent <= 100 ? SS_STATUS_OK : SS_STATUS_INVALID_ARGUMENT;
}

std::uint32_t ss_voice_synthesize_to_audio(
    ss_audio_request_handle_t, std::uint64_t, const wchar_t*, std::uint32_t,
    ss_natural_synthesis_result_t* result)
{
    if (result && result->size == sizeof(ss_natural_synthesis_result_t)) {
        result->status = SS_STATUS_CLOSED;
        result->generated_frames = 0;
        result->synthesis_duration_us = 0;
        result->buffered_frames_after_submit = 0;
    }
    return SS_STATUS_CLOSED;
}

int ss_voice_stop() { return 0; }

void ss_voice_shutdown() {}

std::uint32_t ss_voice_last_error(char* buffer, std::uint32_t capacity)
{
    return selectspeak::abi::CopyString(unavailable, buffer, capacity);
}
