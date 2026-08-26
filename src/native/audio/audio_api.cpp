#include "audio_engine.h"

#include <memory>
#include <mutex>

namespace selectspeak::audio {
namespace {

std::mutex production_mutex;
std::unique_ptr<AudioEngine> production_engine;

}  // namespace

AudioEngine& ProductionAudioEngine()
{
    std::lock_guard lock(production_mutex);
    if (!production_engine) {
        production_engine = std::make_unique<AudioEngine>(CreateXAudio2Sink());
    }
    return *production_engine;
}

void ShutdownProductionAudioEngine()
{
    std::unique_ptr<AudioEngine> engine;
    {
        std::lock_guard lock(production_mutex);
        engine = std::move(production_engine);
    }
    if (engine) {
        engine->Shutdown();
    }
}

}  // namespace selectspeak::audio

std::uint32_t ss_audio_request_create(
    const std::uint64_t request_id, const ss_audio_format_t* const format,
    const std::uint32_t request_text_length_utf16,
    const ss_audio_event_callback_t callback, void* const context,
    ss_audio_request_handle_t* const handle)
{
    return selectspeak::audio::ProductionAudioEngine().Create(
        request_id, format, request_text_length_utf16, callback, context,
        handle);
}

std::uint32_t ss_audio_request_submit(
    const ss_audio_request_handle_t handle, const void* const pcm,
    const std::uint64_t pcm_byte_length,
    const ss_audio_boundary_t* const boundaries,
    const std::uint32_t boundary_count,
    ss_audio_submit_result_t* const result)
{
    return selectspeak::audio::ProductionAudioEngine().Submit(
        handle, pcm, pcm_byte_length, boundaries, boundary_count, result);
}

std::uint32_t ss_audio_request_finish_input(
    const ss_audio_request_handle_t handle)
{
    return selectspeak::audio::ProductionAudioEngine().FinishInput(handle);
}

std::uint32_t ss_audio_request_pause(const ss_audio_request_handle_t handle)
{
    return selectspeak::audio::ProductionAudioEngine().Pause(handle);
}

std::uint32_t ss_audio_request_resume(const ss_audio_request_handle_t handle)
{
    return selectspeak::audio::ProductionAudioEngine().Resume(handle);
}

std::uint32_t ss_audio_request_stop(const ss_audio_request_handle_t handle,
                                    const std::uint32_t terminal_reason)
{
    return selectspeak::audio::ProductionAudioEngine().Stop(handle,
                                                             terminal_reason);
}

std::uint32_t ss_audio_request_destroy(
    const ss_audio_request_handle_t handle)
{
    return selectspeak::audio::ProductionAudioEngine().Destroy(handle);
}
