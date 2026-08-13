#include "../api.h"

#include <algorithm>
#include <cstring>
#include <string>

namespace {
const std::string unavailable =
    "Natural Voice support was omitted from this SelectSpeak native build";
}

std::uint32_t ss_voice_list(ss_voice_callback_t, void*) { return 0; }

int ss_voice_initialize(const wchar_t*) { return 1; }

void ss_voice_set_audio_callback(ss_audio_callback_t, void*) {}

void ss_voice_set_word_callback(ss_word_callback_t, void*) {}

void ss_voice_set_finished_callback(ss_finished_callback_t, void*) {}

int ss_voice_speak(const wchar_t*) { return 1; }

int ss_voice_stop() { return 0; }

void ss_voice_shutdown() {}

std::uint32_t ss_voice_last_error(char* buffer, std::uint32_t capacity)
{
    const auto required = static_cast<std::uint32_t>(unavailable.size() + 1);
    if (buffer && capacity) {
        const auto count = std::min(capacity - 1, required - 1);
        std::memcpy(buffer, unavailable.data(), count);
        buffer[count] = '\0';
    }
    return required;
}
