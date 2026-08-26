#include "../api.h"

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
#include <iterator>
#include <mutex>
#include <string>
#include <vector>

namespace {

struct Voice {
    std::wstring path;
    std::string name;
};

struct Events {
    std::mutex mutex;
    std::condition_variable changed;
    bool started = false;
    bool played_word = false;
    std::uint32_t terminal = SS_TERMINAL_NONE;
};

void __cdecl CollectVoice(const wchar_t* path, const char* name, const char*,
                          const char*, void* context)
{
    if (path && name) {
        static_cast<std::vector<Voice>*>(context)->push_back({path, name});
    }
}

void __cdecl OnAudioEvent(const ss_audio_event_t* event, void* context)
{
    if (!event || event->size != sizeof(ss_audio_event_t)) {
        return;
    }
    auto& events = *static_cast<Events*>(context);
    {
        std::lock_guard lock(events.mutex);
        if (event->kind == SS_AUDIO_EVENT_STARTED) {
            events.started = true;
        } else if (event->kind == SS_AUDIO_EVENT_PLAYED_WORD) {
            events.played_word = true;
        } else if (event->kind == SS_AUDIO_EVENT_TERMINAL) {
            events.terminal = event->terminal_status;
        }
    }
    events.changed.notify_all();
}

}  // namespace

int main()
{
    std::vector<Voice> voices;
    ss_voice_list(CollectVoice, &voices);
    if (voices.empty()) {
        std::cerr << "No installed Natural Voice is available\n";
        return 2;
    }

    bool initialized = false;
    for (const auto& voice : voices) {
        if (ss_voice_initialize(voice.path.c_str(), voice.name.c_str()) == 0) {
            initialized = true;
            break;
        }
    }
    if (!initialized) {
        std::cerr << "No installed Natural Voice could be initialized\n";
        return 3;
    }
    ss_voice_set_volume(5);

    constexpr std::uint64_t request_id = 1;
    constexpr wchar_t text[] = L"SelectSpeak native integration test.";
    const ss_audio_format_t format{sizeof(format), 24'000, 1,
                                   SS_SAMPLE_FORMAT_PCM_S16_LE};
    Events events;
    ss_audio_request_handle_t handle = SS_INVALID_AUDIO_REQUEST_HANDLE;
    auto status = ss_audio_request_create(
        request_id, &format,
        static_cast<std::uint32_t>(std::size(text) - 1), OnAudioEvent, &events,
        &handle);
    if (status != SS_STATUS_OK) {
        std::cerr << "Audio request creation failed: " << status << '\n';
        ss_voice_shutdown();
        return 4;
    }

    ss_natural_synthesis_result_t synthesis{sizeof(synthesis), 0, 0, 0, 0};
    status = ss_voice_synthesize_to_audio(handle, request_id, text, 0,
                                          &synthesis);
    if (status == SS_STATUS_OK) {
        status = ss_audio_request_finish_input(handle);
    }

    bool completed = false;
    if (status == SS_STATUS_OK) {
        std::unique_lock lock(events.mutex);
        completed = events.changed.wait_for(lock, std::chrono::seconds(15), [&] {
            return events.terminal != SS_TERMINAL_NONE;
        });
        completed = completed && events.started && events.played_word &&
                    events.terminal == SS_TERMINAL_COMPLETED;
    }

    ss_audio_request_destroy(handle);
    ss_voice_shutdown();
    if (!completed || synthesis.generated_frames == 0) {
        std::cerr << "Natural-to-audio smoke failed: status=" << status
                  << " frames=" << synthesis.generated_frames << '\n';
        return 5;
    }
    std::cout << "Natural Voice direct-audio smoke passed\n";
    return 0;
}
