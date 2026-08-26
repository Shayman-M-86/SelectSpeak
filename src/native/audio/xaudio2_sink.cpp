#include "audio_engine.h"

#include <windows.h>
#include <xaudio2.h>

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <thread>

namespace selectspeak::audio {
namespace {

class XAudio2EngineEvents final : public IXAudio2EngineCallback {
public:
    void STDMETHODCALLTYPE OnProcessingPassStart() noexcept override {}
    void STDMETHODCALLTYPE OnProcessingPassEnd() noexcept override {}
    void STDMETHODCALLTYPE OnCriticalError(HRESULT) noexcept override
    {
        auto* const notifications = active_.load(std::memory_order_acquire);
        if (notifications != nullptr) {
            notifications->OnVoiceError(SS_STATUS_DEVICE_ERROR);
        }
    }

    void SetActive(VoiceNotifications* const notifications) noexcept
    {
        active_.store(notifications, std::memory_order_release);
    }

    void Clear(VoiceNotifications* const notifications) noexcept
    {
        auto* expected = notifications;
        active_.compare_exchange_strong(expected, nullptr,
                                        std::memory_order_acq_rel);
    }

private:
    std::atomic<VoiceNotifications*> active_{nullptr};
};

class XAudio2Voice final : public AudioVoice,
                           private IXAudio2VoiceCallback {
public:
    XAudio2Voice(IXAudio2* const engine, const ss_audio_format_t& format,
                 VoiceNotifications& notifications,
                 XAudio2EngineEvents& engine_events) noexcept
        : notifications_(notifications), engine_events_(engine_events)
    {
        engine_events_.SetActive(&notifications_);
        WAVEFORMATEX wave_format{};
        wave_format.wFormatTag = WAVE_FORMAT_PCM;
        wave_format.nChannels = static_cast<WORD>(format.channel_count);
        wave_format.nSamplesPerSec = format.sample_rate_hz;
        wave_format.wBitsPerSample = 16;
        wave_format.nBlockAlign = static_cast<WORD>(
            format.channel_count * sizeof(std::int16_t));
        wave_format.nAvgBytesPerSec =
            wave_format.nSamplesPerSec * wave_format.nBlockAlign;
        result_ = engine->CreateSourceVoice(
            &voice_, &wave_format, 0, XAUDIO2_DEFAULT_FREQ_RATIO, this);
    }

    ~XAudio2Voice() override
    {
        Destroy();
    }

    bool Ready() const noexcept
    {
        return SUCCEEDED(result_) && voice_ != nullptr;
    }

    bool Submit(const std::uint8_t* const pcm,
                const std::uint32_t byte_count, void* const context,
                const bool end_of_stream) noexcept override
    {
        if (voice_ == nullptr) {
            return false;
        }
        XAUDIO2_BUFFER buffer{};
        buffer.Flags = end_of_stream ? XAUDIO2_END_OF_STREAM : 0;
        buffer.AudioBytes = byte_count;
        buffer.pAudioData = pcm;
        buffer.pContext = context;
        return SUCCEEDED(voice_->SubmitSourceBuffer(&buffer));
    }

    bool Start() noexcept override
    {
        return voice_ != nullptr && SUCCEEDED(voice_->Start(0));
    }

    bool Pause() noexcept override
    {
        return voice_ != nullptr && SUCCEEDED(voice_->Stop(0));
    }

    bool GetState(VoiceState& state) noexcept override
    {
        if (voice_ == nullptr) {
            return false;
        }
        XAUDIO2_VOICE_STATE native_state{};
        voice_->GetState(&native_state, 0);
        state.samples_played = native_state.SamplesPlayed;
        state.buffers_queued = native_state.BuffersQueued;
        return true;
    }

    void Destroy() noexcept override
    {
        engine_events_.Clear(&notifications_);
        if (voice_ != nullptr) {
            voice_->DestroyVoice();
            voice_ = nullptr;
        }
    }

private:
    void STDMETHODCALLTYPE OnVoiceProcessingPassStart(UINT32) noexcept override {}
    void STDMETHODCALLTYPE OnVoiceProcessingPassEnd() noexcept override
    {
        notifications_.OnProcessingPassEnd();
    }
    void STDMETHODCALLTYPE OnStreamEnd() noexcept override
    {
        notifications_.OnStreamEnd();
    }
    void STDMETHODCALLTYPE OnBufferStart(void*) noexcept override {}
    void STDMETHODCALLTYPE OnBufferEnd(void* const context) noexcept override
    {
        notifications_.OnBufferEnd(context);
    }
    void STDMETHODCALLTYPE OnLoopEnd(void*) noexcept override {}
    void STDMETHODCALLTYPE OnVoiceError(void*, HRESULT) noexcept override
    {
        notifications_.OnVoiceError(SS_STATUS_DEVICE_ERROR);
    }

    VoiceNotifications& notifications_;
    XAudio2EngineEvents& engine_events_;
    IXAudio2SourceVoice* voice_ = nullptr;
    HRESULT result_ = E_FAIL;
};

class XAudio2Sink final : public AudioSink {
public:
    bool Initialize() noexcept
    {
        std::unique_lock lock(mutex_);
        runtime_thread_ = std::thread(&XAudio2Sink::RuntimeMain, this);
        ready_changed_.wait(lock, [&] { return startup_complete_; });
        const bool ready = ready_;
        lock.unlock();
        if (!ready && runtime_thread_.joinable()) {
            runtime_thread_.join();
        }
        return ready;
    }

    std::unique_ptr<AudioVoice> CreateVoice(
        const ss_audio_format_t& format,
        VoiceNotifications& notifications) noexcept override
    {
        std::lock_guard lock(mutex_);
        if (!ready_ || stopping_ || engine_ == nullptr) {
            return nullptr;
        }
        auto voice = std::make_unique<XAudio2Voice>(
            engine_, format, notifications, engine_events_);
        return voice->Ready() ? std::move(voice) : nullptr;
    }

    std::uint64_t OutputLatencyFrames(
        const std::uint32_t source_sample_rate) noexcept override
    {
        std::lock_guard lock(mutex_);
        if (engine_ == nullptr || mastering_sample_rate_ == 0) {
            return 0;
        }
        XAUDIO2_PERFORMANCE_DATA performance{};
        engine_->GetPerformanceData(&performance);
        return static_cast<std::uint64_t>(performance.CurrentLatencyInSamples) *
               source_sample_rate / mastering_sample_rate_;
    }

    void Shutdown() noexcept override
    {
        std::thread runtime;
        {
            std::lock_guard lock(mutex_);
            if (!runtime_thread_.joinable()) {
                return;
            }
            stopping_ = true;
            ready_changed_.notify_all();
            runtime = std::move(runtime_thread_);
        }
        runtime.join();
    }

    ~XAudio2Sink() override
    {
        Shutdown();
    }

private:
    void RuntimeMain() noexcept
    {
        const HRESULT com_result =
            CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        const bool com_initialized = SUCCEEDED(com_result);
        HRESULT result = com_initialized
                             ? XAudio2Create(&engine_, 0,
                                             XAUDIO2_DEFAULT_PROCESSOR)
                             : com_result;
        bool callbacks_registered = false;
        if (SUCCEEDED(result)) {
            result = engine_->RegisterForCallbacks(&engine_events_);
            callbacks_registered = SUCCEEDED(result);
        }
        if (SUCCEEDED(result)) {
            result = engine_->CreateMasteringVoice(&mastering_voice_);
        }
        if (SUCCEEDED(result)) {
            XAUDIO2_VOICE_DETAILS details{};
            mastering_voice_->GetVoiceDetails(&details);
            mastering_sample_rate_ = details.InputSampleRate;
            if (mastering_sample_rate_ == 0) {
                result = E_FAIL;
            }
        }

        {
            std::unique_lock lock(mutex_);
            ready_ = SUCCEEDED(result);
            startup_complete_ = true;
            ready_changed_.notify_all();
            if (ready_) {
                ready_changed_.wait(lock, [&] { return stopping_; });
            }
            ready_ = false;
        }

        if (mastering_voice_ != nullptr) {
            mastering_voice_->DestroyVoice();
            mastering_voice_ = nullptr;
        }
        if (engine_ != nullptr) {
            if (callbacks_registered) {
                engine_->UnregisterForCallbacks(&engine_events_);
            }
            engine_->Release();
            engine_ = nullptr;
        }
        mastering_sample_rate_ = 0;
        if (com_initialized) {
            CoUninitialize();
        }
    }

    std::mutex mutex_;
    std::condition_variable ready_changed_;
    std::thread runtime_thread_;
    XAudio2EngineEvents engine_events_;
    IXAudio2* engine_ = nullptr;
    IXAudio2MasteringVoice* mastering_voice_ = nullptr;
    std::uint32_t mastering_sample_rate_ = 0;
    bool startup_complete_ = false;
    bool ready_ = false;
    bool stopping_ = false;
};

}  // namespace

std::shared_ptr<AudioSink> CreateXAudio2Sink() noexcept
{
    auto sink = std::make_shared<XAudio2Sink>();
    return sink->Initialize() ? std::move(sink) : nullptr;
}

}  // namespace selectspeak::audio
