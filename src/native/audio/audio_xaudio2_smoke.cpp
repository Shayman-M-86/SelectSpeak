#include "../api.h"

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <vector>

namespace {

struct SmokeState {
    std::mutex mutex;
    std::condition_variable changed;
    std::uint32_t started = 0;
    std::uint32_t words = 0;
    std::uint32_t terminals = 0;
    std::uint32_t terminal_status = SS_TERMINAL_NONE;
    std::uint32_t error_status = SS_STATUS_OK;
};

void __cdecl OnAudioEvent(const ss_audio_event_t* const event,
                          void* const context)
{
    if (event == nullptr || context == nullptr) {
        return;
    }
    auto& state = *static_cast<SmokeState*>(context);
    {
        std::lock_guard lock(state.mutex);
        if (event->kind == SS_AUDIO_EVENT_STARTED) {
            ++state.started;
        } else if (event->kind == SS_AUDIO_EVENT_PLAYED_WORD) {
            ++state.words;
        } else if (event->kind == SS_AUDIO_EVENT_TERMINAL) {
            ++state.terminals;
            state.terminal_status = event->terminal_status;
            state.error_status = event->status;
        }
    }
    state.changed.notify_all();
}

}  // namespace

int main()
{
    constexpr std::uint32_t sample_rate = 24'000;
    constexpr std::uint64_t frames_per_buffer = sample_rate / 10;
    ss_audio_format_t format{sizeof(format), sample_rate, 1,
                             SS_SAMPLE_FORMAT_PCM_S16_LE};
    SmokeState state;
    ss_audio_request_handle_t handle = SS_INVALID_AUDIO_REQUEST_HANDLE;
    const auto create_status = ss_audio_request_create(
        1, &format, 4, OnAudioEvent, &state, &handle);
    if (create_status != SS_STATUS_OK) {
        std::cerr << "audio smoke create failed with status " << create_status
                  << '\n';
        ss_shutdown();
        return 2;
    }

    std::vector<std::int16_t> silence(
        static_cast<std::size_t>(frames_per_buffer), 0);
    const ss_audio_boundary_t boundary{0, 0, 4};
    for (std::uint32_t index = 0; index < 3; ++index) {
        ss_audio_submit_result_t result{sizeof(result), 0, 0, 0};
        const auto submit_status = ss_audio_request_submit(
            handle, silence.data(), silence.size() * sizeof(std::int16_t),
            index == 0 ? &boundary : nullptr, index == 0 ? 1u : 0u, &result);
        if (submit_status != SS_STATUS_OK ||
            result.accepted_frames != frames_per_buffer) {
            std::cerr << "audio smoke submit failed with status "
                      << submit_status << '\n';
            ss_audio_request_destroy(handle);
            ss_shutdown();
            return 3;
        }
    }
    if (ss_audio_request_finish_input(handle) != SS_STATUS_OK) {
        std::cerr << "audio smoke finish failed\n";
        ss_audio_request_destroy(handle);
        ss_shutdown();
        return 4;
    }

    bool completed = false;
    {
        std::unique_lock lock(state.mutex);
        completed = state.changed.wait_for(lock, std::chrono::seconds(5), [&] {
            return state.terminals != 0;
        });
    }
    const auto destroy_status = ss_audio_request_destroy(handle);

    if (!completed || state.started != 1 || state.words != 1 ||
        state.terminals != 1 ||
        state.terminal_status != SS_TERMINAL_COMPLETED ||
        state.error_status != SS_STATUS_OK || destroy_status != SS_STATUS_OK) {
        std::cerr << "audio smoke lifecycle mismatch: started=" << state.started
                  << " words=" << state.words
                  << " terminals=" << state.terminals
                  << " terminal_status=" << state.terminal_status
                  << " error_status=" << state.error_status
                  << " destroy_status=" << destroy_status << '\n';
        ss_shutdown();
        return 5;
    }

    SmokeState control_state;
    ss_audio_request_handle_t control_handle =
        SS_INVALID_AUDIO_REQUEST_HANDLE;
    if (ss_audio_request_create(2, &format, 4, OnAudioEvent,
                                &control_state, &control_handle) !=
        SS_STATUS_OK) {
        std::cerr << "audio control smoke create failed\n";
        ss_shutdown();
        return 6;
    }
    for (std::uint32_t index = 0; index < 4; ++index) {
        ss_audio_submit_result_t result{sizeof(result), 0, 0, 0};
        if (ss_audio_request_submit(
                control_handle, silence.data(),
                silence.size() * sizeof(std::int16_t), nullptr, 0,
                &result) != SS_STATUS_OK) {
            std::cerr << "audio control smoke submit failed\n";
            ss_audio_request_destroy(control_handle);
            ss_shutdown();
            return 7;
        }
    }
    if (ss_audio_request_pause(control_handle) != SS_STATUS_OK ||
        ss_audio_request_resume(control_handle) != SS_STATUS_OK ||
        ss_audio_request_stop(control_handle, SS_TERMINAL_CANCELLED) !=
            SS_STATUS_OK) {
        std::cerr << "audio control smoke lifecycle failed\n";
        ss_audio_request_destroy(control_handle);
        ss_shutdown();
        return 8;
    }
    {
        std::unique_lock lock(control_state.mutex);
        completed = control_state.changed.wait_for(
            lock, std::chrono::seconds(2),
            [&] { return control_state.terminals != 0; });
    }
    if (!completed || control_state.started != 1 ||
        control_state.terminals != 1 ||
        control_state.terminal_status != SS_TERMINAL_CANCELLED ||
        ss_audio_request_destroy(control_handle) != SS_STATUS_OK) {
        std::cerr << "audio control smoke settlement mismatch\n";
        ss_shutdown();
        return 9;
    }
    ss_shutdown();
    std::cout << "XAudio2 request smoke passed\n";
    return 0;
}
