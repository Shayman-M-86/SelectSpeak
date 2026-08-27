#pragma once

#include "../api.h"

#include <cstdint>
#include <memory>

namespace selectspeak::audio {

struct VoiceState {
    std::uint64_t samples_played = 0;
    std::uint32_t buffers_queued = 0;
};

class VoiceNotifications {
public:
    virtual ~VoiceNotifications() = default;
    virtual void OnBufferEnd(void* context) noexcept = 0;
    virtual void OnStreamEnd() noexcept = 0;
    virtual void OnProcessingPassEnd() noexcept = 0;
    virtual void OnVoiceError(std::uint32_t status) noexcept = 0;
};

class AudioVoice {
public:
    virtual ~AudioVoice() = default;
    virtual bool Submit(const std::uint8_t* pcm, std::uint32_t byte_count,
                        void* context, bool end_of_stream) noexcept = 0;
    virtual bool Start() noexcept = 0;
    virtual bool Pause() noexcept = 0;
    virtual bool GetState(VoiceState& state) noexcept = 0;
    virtual void Destroy() noexcept = 0;
};

class AudioSink {
public:
    virtual ~AudioSink() = default;
    virtual std::unique_ptr<AudioVoice> CreateVoice(
        const ss_audio_format_t& format,
        VoiceNotifications& notifications) noexcept = 0;
    virtual std::uint64_t OutputLatencyFrames(
        std::uint32_t source_sample_rate) noexcept = 0;
    virtual void Shutdown() noexcept = 0;
};

class AudioEngine final {
public:
    explicit AudioEngine(std::shared_ptr<AudioSink> sink);
    ~AudioEngine();
    AudioEngine(const AudioEngine&) = delete;
    AudioEngine& operator=(const AudioEngine&) = delete;

    std::uint32_t Create(std::uint64_t request_id,
                         const ss_audio_format_t* format,
                         std::uint32_t request_text_length_utf16,
                         ss_audio_event_callback_t callback, void* context,
                         ss_audio_request_handle_t* handle);
    std::uint32_t Submit(ss_audio_request_handle_t handle, const void* pcm,
                         std::uint64_t pcm_byte_length,
                         const ss_audio_boundary_t* boundaries,
                         std::uint32_t boundary_count,
                         ss_audio_submit_result_t* result);
    std::uint32_t SubmitForRequest(
        ss_audio_request_handle_t handle, std::uint64_t request_id,
        const void* pcm, std::uint64_t pcm_byte_length,
        const ss_audio_boundary_t* boundaries, std::uint32_t boundary_count,
        ss_audio_submit_result_t* result);
    std::uint32_t ValidateProducerTextRange(
        ss_audio_request_handle_t handle, std::uint64_t request_id,
        std::uint32_t text_position_utf16,
        std::uint32_t text_length_utf16);
    std::uint32_t FinishInput(ss_audio_request_handle_t handle);
    std::uint32_t Pause(ss_audio_request_handle_t handle);
    std::uint32_t Resume(ss_audio_request_handle_t handle);
    std::uint32_t Stop(ss_audio_request_handle_t handle,
                       std::uint32_t terminal_reason);
    std::uint32_t Destroy(ss_audio_request_handle_t handle);
    void Shutdown();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

std::shared_ptr<AudioSink> CreateXAudio2Sink() noexcept;
AudioEngine& ProductionAudioEngine();
void ShutdownProductionAudioEngine();

}  // namespace selectspeak::audio
