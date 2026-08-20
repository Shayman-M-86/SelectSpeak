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

int ss_voice_stop() { return 0; }

void ss_voice_shutdown() {}

std::uint32_t ss_voice_last_error(char* buffer, std::uint32_t capacity)
{
    return selectspeak::abi::CopyString(unavailable, buffer, capacity);
}
