// Package C - focused XAudio2 feasibility check.
//
// NON-PRODUCTION evidence code. The engine/mastering voice lives for the run;
// each SelectSpeak request receives a fresh source voice. This intentionally
// avoids testing or designing cross-request source-voice reuse.

#include <windows.h>
#include <xaudio2.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr uint32_t kSampleRate = 24000;
constexpr uint32_t kChannels = 1;
constexpr uint32_t kBytesPerFrame = 2;
constexpr uint64_t kBufferFrames = kSampleRate / 10; // 100 ms.

int g_passed = 0;
int g_failed = 0;

void observation(const char* scenario, const char* name, uint64_t value) {
    std::printf("OBS   %-18s %-38s %llu\n", scenario, name,
                static_cast<unsigned long long>(value));
}

void note(const char* scenario, const char* text) {
    std::printf("NOTE  %-18s %s\n", scenario, text);
}

void check(const char* scenario, const char* name, bool passed) {
    passed ? ++g_passed : ++g_failed;
    std::printf("CHECK %-18s %-38s %s\n", scenario, name,
                passed ? "PASS" : "FAIL");
}

uint64_t frames_to_ms(uint64_t frames) {
    return frames * 1000ull / kSampleRate;
}

struct Segment {
    explicit Segment(uint64_t segment_id) : id(segment_id) {}

    uint64_t id;
    std::vector<int16_t> samples;
    std::atomic<bool> ended{false};
};

void fill_quiet_tone(Segment& segment, uint64_t frames, double frequency) {
    segment.samples.resize(static_cast<size_t>(frames));
    for (uint64_t frame = 0; frame < frames; ++frame) {
        const double seconds = static_cast<double>(frame) / kSampleRate;
        const double value = 0.025 * std::sin(6.283185307179586 * frequency * seconds);
        segment.samples[static_cast<size_t>(frame)] =
            static_cast<int16_t>(value * 32767.0);
    }
}

class RequestCallback final : public IXAudio2VoiceCallback {
public:
    HANDLE activity = nullptr;
    std::atomic<uint64_t> buffer_ends{0};
    std::atomic<uint64_t> stream_ends{0};
    std::atomic<uint64_t> processing_passes{0};
    std::atomic<HRESULT> voice_error{S_OK};

    void STDMETHODCALLTYPE OnBufferEnd(void* context) noexcept override {
        if (context != nullptr) {
            static_cast<Segment*>(context)->ended.store(true, std::memory_order_release);
        }
        buffer_ends.fetch_add(1, std::memory_order_relaxed);
        SetEvent(activity);
    }

    void STDMETHODCALLTYPE OnStreamEnd() noexcept override {
        stream_ends.fetch_add(1, std::memory_order_relaxed);
        SetEvent(activity);
    }

    void STDMETHODCALLTYPE OnVoiceProcessingPassEnd() noexcept override {
        processing_passes.fetch_add(1, std::memory_order_relaxed);
        SetEvent(activity);
    }

    void STDMETHODCALLTYPE OnVoiceError(void*, HRESULT error) noexcept override {
        voice_error.store(error, std::memory_order_relaxed);
        SetEvent(activity);
    }

    void STDMETHODCALLTYPE OnVoiceProcessingPassStart(UINT32) noexcept override {}
    void STDMETHODCALLTYPE OnBufferStart(void*) noexcept override {}
    void STDMETHODCALLTYPE OnLoopEnd(void*) noexcept override {}
};

class RequestVoice {
public:
    RequestVoice(IXAudio2* engine, uint64_t request_id) : request_id_(request_id) {
        callback_.activity = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (callback_.activity == nullptr) return;

        WAVEFORMATEX format{};
        format.wFormatTag = WAVE_FORMAT_PCM;
        format.nChannels = static_cast<WORD>(kChannels);
        format.nSamplesPerSec = kSampleRate;
        format.wBitsPerSample = 16;
        format.nBlockAlign = static_cast<WORD>(kBytesPerFrame);
        format.nAvgBytesPerSec = kSampleRate * kBytesPerFrame;

        init_result_ = engine->CreateSourceVoice(
            &voice_, &format, 0, XAUDIO2_DEFAULT_FREQ_RATIO, &callback_);
    }

    RequestVoice(const RequestVoice&) = delete;
    RequestVoice& operator=(const RequestVoice&) = delete;

    ~RequestVoice() {
        destroy();
        if (callback_.activity != nullptr) CloseHandle(callback_.activity);
    }

    bool ready() const { return SUCCEEDED(init_result_) && voice_ != nullptr; }
    uint64_t request_id() const { return request_id_; }
    HANDLE activity() const { return callback_.activity; }
    RequestCallback& callback() { return callback_; }

    HRESULT submit(Segment& segment, bool final_buffer) {
        XAUDIO2_BUFFER buffer{};
        buffer.Flags = final_buffer ? XAUDIO2_END_OF_STREAM : 0;
        buffer.AudioBytes = static_cast<UINT32>(
            segment.samples.size() * sizeof(int16_t));
        buffer.pAudioData = reinterpret_cast<const BYTE*>(segment.samples.data());
        buffer.pContext = &segment;
        return voice_->SubmitSourceBuffer(&buffer);
    }

    HRESULT start() { return voice_->Start(0); }
    HRESULT pause() { return voice_->Stop(0); }

    XAUDIO2_VOICE_STATE state() const {
        XAUDIO2_VOICE_STATE result{};
        voice_->GetState(&result, 0);
        return result;
    }

    uint64_t played_frames() const { return state().SamplesPlayed; }

    uint64_t destroy() {
        if (voice_ == nullptr) return 0;
        const auto started = std::chrono::steady_clock::now();
        voice_->DestroyVoice();
        voice_ = nullptr;
        return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now() - started).count());
    }

private:
    uint64_t request_id_;
    IXAudio2SourceVoice* voice_ = nullptr;
    HRESULT init_result_ = E_FAIL;
    RequestCallback callback_;
};

struct Engine {
    IXAudio2* xaudio = nullptr;
    IXAudio2MasteringVoice* mastering = nullptr;
    uint32_t mastering_rate = 0;

    bool initialize() {
        HRESULT result = XAudio2Create(&xaudio, 0, XAUDIO2_DEFAULT_PROCESSOR);
        if (FAILED(result)) return false;
        result = xaudio->CreateMasteringVoice(&mastering);
        if (FAILED(result)) return false;

        XAUDIO2_VOICE_DETAILS details{};
        mastering->GetVoiceDetails(&details);
        mastering_rate = details.InputSampleRate;
        return mastering_rate != 0;
    }

    uint64_t latency_in_source_frames() const {
        XAUDIO2_PERFORMANCE_DATA data{};
        xaudio->GetPerformanceData(&data);
        return static_cast<uint64_t>(data.CurrentLatencyInSamples) * kSampleRate /
               mastering_rate;
    }

    void shutdown() {
        if (mastering != nullptr) {
            mastering->DestroyVoice();
            mastering = nullptr;
        }
        if (xaudio != nullptr) {
            xaudio->Release();
            xaudio = nullptr;
        }
    }
};

bool wait_for_activity(RequestVoice& request, DWORD timeout_ms = 500) {
    return WaitForSingleObject(request.activity(), timeout_ms) == WAIT_OBJECT_0;
}

bool wait_for_played(RequestVoice& request, uint64_t frames, DWORD timeout_ms) {
    const uint64_t deadline = GetTickCount64() + timeout_ms;
    while (request.played_frames() < frames) {
        if (GetTickCount64() >= deadline) return false;
        wait_for_activity(request, 50);
    }
    return true;
}

bool wait_for_stream_end(RequestVoice& request, DWORD timeout_ms) {
    const uint64_t deadline = GetTickCount64() + timeout_ms;
    while (request.callback().stream_ends.load(std::memory_order_relaxed) == 0) {
        if (GetTickCount64() >= deadline) return false;
        wait_for_activity(request, 50);
    }
    return true;
}

void scenario_incremental_boundaries_and_pause(Engine& engine) {
    constexpr const char* scenario = "request_lifecycle";
    RequestVoice request(engine.xaudio, 41);
    check(scenario, "request source voice created", request.ready());
    if (!request.ready()) return;

    std::vector<std::unique_ptr<Segment>> segments;
    for (uint64_t index = 0; index < 10; ++index) {
        auto segment = std::make_unique<Segment>(index + 1);
        fill_quiet_tone(*segment, kBufferFrames, 220.0);
        segments.push_back(std::move(segment));
    }

    size_t next_to_submit = 0;
    uint64_t accepted_frames = 0;
    auto submit_next = [&]() {
        const bool final_buffer = next_to_submit + 1 == segments.size();
        const HRESULT result = request.submit(*segments[next_to_submit], final_buffer);
        if (SUCCEEDED(result)) {
            ++next_to_submit;
            accepted_frames += kBufferFrames;
        }
        return SUCCEEDED(result);
    };

    check(scenario, "initial buffer 1 submitted", submit_next());
    check(scenario, "initial buffer 2 submitted", submit_next());
    check(scenario, "initial buffer 3 submitted", submit_next());
    check(scenario, "source voice started", SUCCEEDED(request.start()));

    const std::vector<uint64_t> boundaries{
        kSampleRate / 5, 2 * kSampleRate / 5,
        3 * kSampleRate / 5, 4 * kSampleRate / 5};
    size_t next_boundary = 0;
    uint64_t max_boundary_lateness = 0;
    uint64_t max_reported_latency = 0;
    uint64_t max_observed_played = 0;
    uint64_t max_estimated_audible = 0;
    bool pause_checked = false;
    bool pause_position_stable = false;
    const uint64_t deadline = GetTickCount64() + 6000;

    while (request.callback().stream_ends.load(std::memory_order_relaxed) == 0 &&
           GetTickCount64() < deadline) {
        wait_for_activity(request, 100);
        const XAUDIO2_VOICE_STATE state = request.state();
        max_observed_played = std::max(max_observed_played, state.SamplesPlayed);
        const uint64_t latency = engine.latency_in_source_frames();
        max_reported_latency = std::max(max_reported_latency, latency);
        const uint64_t estimated_audible =
            state.SamplesPlayed > latency ? state.SamplesPlayed - latency : 0;
        max_estimated_audible = std::max(max_estimated_audible, estimated_audible);

        while (next_to_submit < segments.size() && state.BuffersQueued < 3) {
            if (!submit_next()) break;
        }

        while (next_boundary < boundaries.size() &&
               estimated_audible >= boundaries[next_boundary]) {
            max_boundary_lateness = std::max(
                max_boundary_lateness,
                estimated_audible - boundaries[next_boundary]);
            ++next_boundary;
        }

        if (!pause_checked && state.SamplesPlayed >= kSampleRate / 4) {
            request.pause();
            const uint64_t before = request.played_frames();
            std::this_thread::sleep_for(std::chrono::milliseconds(150));
            const uint64_t after = request.played_frames();
            pause_position_stable = after - before <= kSampleRate / 100;
            request.start();
            pause_checked = true;
        }
    }

    const bool stream_ended = request.callback().stream_ends.load() == 1;
    const XAUDIO2_VOICE_STATE final_state = request.state();
    uint64_t reclaimed = 0;
    for (const auto& segment : segments) {
        if (segment->ended.load(std::memory_order_acquire)) ++reclaimed;
    }

    observation(scenario, "request_id", request.request_id());
    observation(scenario, "accepted_frames", accepted_frames);
    observation(scenario, "max_observed_played_frames", max_observed_played);
    observation(scenario, "max_estimated_audible_frames", max_estimated_audible);
    observation(scenario, "samples_after_stream_end", final_state.SamplesPlayed);
    observation(scenario, "buffer_end_callbacks", request.callback().buffer_ends.load());
    observation(scenario, "processing_pass_signals", request.callback().processing_passes.load());
    observation(scenario, "max_boundary_lateness_ms", frames_to_ms(max_boundary_lateness));
    observation(scenario, "max_reported_output_latency_ms", frames_to_ms(max_reported_latency));

    check(scenario, "incremental stream ended", stream_ended);
    check(scenario, "audible estimate reached final boundary",
          max_estimated_audible >= boundaries.back());
    check(scenario, "every normal buffer reclaimed", reclaimed == segments.size());
    check(scenario, "pause preserved position", pause_checked && pause_position_stable);
    check(scenario, "all word boundaries dispatched", next_boundary == boundaries.size());
    check(scenario, "event-driven boundary lateness <= 20ms",
          max_boundary_lateness <= kSampleRate / 50);
    check(scenario, "no XAudio2 voice error", request.callback().voice_error.load() == S_OK);
    note(scenario, "OnVoiceProcessingPassEnd wakes one non-audio dispatcher; no timer polling.");
    note(scenario, "Boundary position subtracts XAudio2's reported output latency from SamplesPlayed.");
    note(scenario, "Completion uses OnBufferEnd plus OnStreamEnd; do not query SamplesPlayed afterward.");

    const uint64_t callbacks_before_destroy =
        request.callback().buffer_ends.load() + request.callback().stream_ends.load();
    const uint64_t destroy_us = request.destroy();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    const uint64_t callbacks_after_destroy =
        request.callback().buffer_ends.load() + request.callback().stream_ends.load();
    observation(scenario, "destroy_voice_us", destroy_us);
    check(scenario, "no callback after DestroyVoice returns",
          callbacks_before_destroy == callbacks_after_destroy);
}

void scenario_cancel_and_supersede(Engine& engine) {
    constexpr const char* scenario = "cancel_supersede";
    RequestVoice old_request(engine.xaudio, 42);
    check(scenario, "old request source voice created", old_request.ready());
    if (!old_request.ready()) return;

    std::vector<std::unique_ptr<Segment>> old_segments;
    for (uint64_t index = 0; index < 8; ++index) {
        auto segment = std::make_unique<Segment>(100 + index);
        fill_quiet_tone(*segment, kSampleRate / 4, 330.0);
        old_request.submit(*segment, index + 1 == 8);
        old_segments.push_back(std::move(segment));
    }
    old_request.start();
    check(scenario, "old request began playback",
          wait_for_played(old_request, kSampleRate / 5, 3000));

    const uint64_t callbacks_before = old_request.callback().buffer_ends.load() +
                                      old_request.callback().stream_ends.load();
    const uint64_t destroy_us = old_request.destroy();
    const uint64_t callbacks_at_return = old_request.callback().buffer_ends.load() +
                                         old_request.callback().stream_ends.load();
    std::this_thread::sleep_for(std::chrono::milliseconds(120));
    const uint64_t callbacks_later = old_request.callback().buffer_ends.load() +
                                     old_request.callback().stream_ends.load();

    observation(scenario, "old_callbacks_before_destroy", callbacks_before);
    observation(scenario, "old_callbacks_at_destroy_return", callbacks_at_return);
    observation(scenario, "destroy_voice_us", destroy_us);
    check(scenario, "destroy settled under 50ms", destroy_us < 50000);
    check(scenario, "old request stayed quiescent", callbacks_at_return == callbacks_later);
    note(scenario, "After DestroyVoice returns, all old PCM is safe to free even without OnBufferEnd.");

    RequestVoice new_request(engine.xaudio, 43);
    check(scenario, "superseding source voice created", new_request.ready());
    if (!new_request.ready()) return;
    check(scenario, "new request SamplesPlayed starts at zero",
          new_request.played_frames() == 0);

    std::vector<std::unique_ptr<Segment>> new_segments;
    for (uint64_t index = 0; index < 3; ++index) {
        auto segment = std::make_unique<Segment>(200 + index);
        fill_quiet_tone(*segment, kBufferFrames, 550.0);
        check(scenario, "superseding buffer submitted",
              SUCCEEDED(new_request.submit(*segment, index + 1 == 3)));
        new_segments.push_back(std::move(segment));
    }
    check(scenario, "superseding request started", SUCCEEDED(new_request.start()));
    check(scenario, "superseding position advanced",
          wait_for_played(new_request, kBufferFrames / 2, 2000));
    check(scenario, "superseding request completed", wait_for_stream_end(new_request, 3000));
    check(scenario, "superseding buffers completed",
          new_request.callback().buffer_ends.load() == new_segments.size());
    check(scenario, "superseding stream ended once",
          new_request.callback().stream_ends.load() == 1);
    check(scenario, "no superseding voice error",
          new_request.callback().voice_error.load() == S_OK);
    new_request.destroy();
}

void report_capacity_policy() {
    constexpr const char* scenario = "capacity_policy";
    constexpr uint64_t high_frames = 3 * kSampleRate;
    constexpr uint64_t low_frames = 1 * kSampleRate;
    constexpr uint64_t hard_frames = 4 * kSampleRate;
    constexpr uint64_t buffers_at_hard_limit = hard_frames / kBufferFrames;

    observation(scenario, "provisional_low_water_ms", frames_to_ms(low_frames));
    observation(scenario, "provisional_high_water_ms", frames_to_ms(high_frames));
    observation(scenario, "provisional_hard_capacity_ms", frames_to_ms(hard_frames));
    observation(scenario, "100ms_buffers_at_hard_capacity", buffers_at_hard_limit);
    observation(scenario, "XAudio2_queue_limit", XAUDIO2_MAX_QUEUED_BUFFERS);
    check(scenario, "provisional capacity fits XAudio2 queue",
          buffers_at_hard_limit < XAUDIO2_MAX_QUEUED_BUFFERS);
    note(scenario, "Values are provisional policy, not frozen API constants.");
    note(scenario, "Large Supertonic segments must be sliced before bounded admission.");
}

} // namespace

int main() {
    std::printf("=== Package C: request-scoped XAudio2 feasibility check ===\n");
    std::printf("format: pcm_s16_le %u Hz, %u channel\n\n", kSampleRate, kChannels);

    const HRESULT com_result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(com_result)) {
        std::printf("FATAL CoInitializeEx 0x%08lX\n",
                    static_cast<unsigned long>(com_result));
        return 2;
    }

    Engine engine;
    if (!engine.initialize()) {
        std::printf("FATAL could not initialize XAudio2/default output device\n");
        CoUninitialize();
        return 2;
    }

    observation("engine", "mastering_sample_rate", engine.mastering_rate);
    scenario_incremental_boundaries_and_pause(engine);
    std::printf("\n");
    scenario_cancel_and_supersede(engine);
    std::printf("\n");
    report_capacity_policy();

    engine.shutdown();
    CoUninitialize();

    std::printf("\n=== summary: %d passed, %d failed ===\n", g_passed, g_failed);
    return g_failed == 0 ? 0 : 1;
}
