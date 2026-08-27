#include "audio_engine.h"
#include "pcm_volume.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

using selectspeak::audio::AudioEngine;
using selectspeak::audio::AudioSink;
using selectspeak::audio::AudioVoice;
using selectspeak::audio::VoiceNotifications;
using selectspeak::audio::VoiceState;

int failures = 0;

void Expect(const bool condition, const char* const message)
{
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

struct RecordedEvent {
    std::uint32_t kind = 0;
    std::uint64_t request_id = 0;
    std::uint32_t terminal_status = 0;
    std::uint32_t status = 0;
    std::uint32_t text_position = 0;
    std::uint32_t text_length = 0;
    std::uint64_t buffered_frames = 0;
    std::string diagnostic;
};

class Recorder {
public:
    static void __cdecl Callback(const ss_audio_event_t* const event,
                                 void* const context)
    {
        if (event == nullptr || context == nullptr) {
            return;
        }
        auto& recorder = *static_cast<Recorder*>(context);
        RecordedEvent copy{};
        copy.kind = event->kind;
        copy.request_id = event->request_id;
        copy.terminal_status = event->terminal_status;
        copy.status = event->status;
        copy.text_position = event->text_position;
        copy.text_length = event->text_length;
        copy.buffered_frames = event->buffered_frames;
        copy.diagnostic = event->diagnostic == nullptr ? "" : event->diagnostic;
        {
            std::lock_guard lock(recorder.mutex_);
            recorder.events_.push_back(std::move(copy));
        }
        recorder.changed_.notify_all();
    }

    bool WaitForKind(const std::uint32_t kind,
                     const std::size_t count = 1)
    {
        std::unique_lock lock(mutex_);
        return changed_.wait_for(lock, std::chrono::seconds(2), [&] {
            return static_cast<std::size_t>(std::count_if(
                       events_.begin(), events_.end(),
                       [kind](const auto& event) { return event.kind == kind; })) >=
                   count;
        });
    }

    std::vector<RecordedEvent> Snapshot() const
    {
        std::lock_guard lock(mutex_);
        return events_;
    }

private:
    mutable std::mutex mutex_;
    std::condition_variable changed_;
    std::vector<RecordedEvent> events_;
};

struct FakeVoiceState {
    std::mutex mutex;
    VoiceNotifications* notifications = nullptr;
    std::deque<void*> contexts;
    std::deque<bool> final_flags;
    std::uint64_t samples_played = 0;
    int starts = 0;
    int pauses = 0;
    int destroys = 0;
    bool fail_submit = false;
    bool fail_start = false;
    bool fail_state = false;
    bool destroyed = false;
};

class FakeVoice final : public AudioVoice {
public:
    explicit FakeVoice(std::shared_ptr<FakeVoiceState> state)
        : state_(std::move(state))
    {
    }

    bool Submit(const std::uint8_t*, const std::uint32_t byte_count,
                void* const context,
                const bool end_of_stream) noexcept override
    {
        std::lock_guard lock(state_->mutex);
        if (state_->destroyed || state_->fail_submit || byte_count == 0) {
            return false;
        }
        state_->contexts.push_back(context);
        state_->final_flags.push_back(end_of_stream);
        return true;
    }

    bool Start() noexcept override
    {
        std::lock_guard lock(state_->mutex);
        ++state_->starts;
        return !state_->destroyed && !state_->fail_start;
    }

    bool Pause() noexcept override
    {
        std::lock_guard lock(state_->mutex);
        ++state_->pauses;
        return !state_->destroyed;
    }

    bool GetState(VoiceState& state) noexcept override
    {
        std::lock_guard lock(state_->mutex);
        if (state_->destroyed || state_->fail_state) {
            return false;
        }
        state.samples_played = state_->samples_played;
        state.buffers_queued = static_cast<std::uint32_t>(state_->contexts.size());
        return true;
    }

    void Destroy() noexcept override
    {
        std::lock_guard lock(state_->mutex);
        if (!state_->destroyed) {
            state_->destroyed = true;
            state_->notifications = nullptr;
            ++state_->destroys;
        }
    }

private:
    std::shared_ptr<FakeVoiceState> state_;
};

class FakeSink final : public AudioSink {
public:
    std::unique_ptr<AudioVoice> CreateVoice(
        const ss_audio_format_t&,
        VoiceNotifications& notifications) noexcept override
    {
        auto state = std::make_shared<FakeVoiceState>();
        state->notifications = &notifications;
        {
            std::lock_guard lock(mutex_);
            voices_.push_back(state);
        }
        return std::make_unique<FakeVoice>(std::move(state));
    }

    std::uint64_t OutputLatencyFrames(std::uint32_t) noexcept override
    {
        return latency_frames;
    }

    void Shutdown() noexcept override
    {
        shutdown = true;
    }

    std::shared_ptr<FakeVoiceState> Voice(const std::size_t index = 0)
    {
        std::lock_guard lock(mutex_);
        return voices_.at(index);
    }

    std::size_t VoiceCount()
    {
        std::lock_guard lock(mutex_);
        return voices_.size();
    }

    void Advance(const std::shared_ptr<FakeVoiceState>& state,
                 const std::uint64_t samples)
    {
        VoiceNotifications* notifications = nullptr;
        {
            std::lock_guard lock(state->mutex);
            state->samples_played = samples;
            notifications = state->notifications;
        }
        if (notifications != nullptr) {
            notifications->OnProcessingPassEnd();
        }
    }

    void EndNext(const std::shared_ptr<FakeVoiceState>& state)
    {
        VoiceNotifications* notifications = nullptr;
        void* context = nullptr;
        bool final_buffer = false;
        {
            std::lock_guard lock(state->mutex);
            if (state->contexts.empty()) {
                return;
            }
            context = state->contexts.front();
            state->contexts.pop_front();
            final_buffer = state->final_flags.front();
            state->final_flags.pop_front();
            notifications = state->notifications;
        }
        if (notifications != nullptr) {
            notifications->OnBufferEnd(context);
            if (final_buffer) {
                notifications->OnStreamEnd();
            }
        }
    }

    void FailVoice(const std::shared_ptr<FakeVoiceState>& state)
    {
        VoiceNotifications* notifications = nullptr;
        {
            std::lock_guard lock(state->mutex);
            notifications = state->notifications;
        }
        if (notifications != nullptr) {
            notifications->OnVoiceError(SS_STATUS_DEVICE_ERROR);
        }
    }

    std::uint64_t latency_frames = 0;
    bool shutdown = false;

private:
    std::mutex mutex_;
    std::vector<std::shared_ptr<FakeVoiceState>> voices_;
};

ss_audio_format_t Format(const std::uint32_t sample_rate = 100)
{
    return ss_audio_format_t{sizeof(ss_audio_format_t), sample_rate, 1,
                             SS_SAMPLE_FORMAT_PCM_S16_LE};
}

std::vector<std::uint8_t> Pcm(const std::uint64_t frames)
{
    return std::vector<std::uint8_t>(static_cast<std::size_t>(frames * 2), 0);
}

ss_audio_request_handle_t Create(AudioEngine& engine, Recorder& recorder,
                                 const std::uint64_t request_id = 1,
                                 const std::uint32_t sample_rate = 100)
{
    auto format = Format(sample_rate);
    ss_audio_request_handle_t handle = SS_INVALID_AUDIO_REQUEST_HANDLE;
    Expect(engine.Create(request_id, &format, 20, Recorder::Callback,
                         &recorder, &handle) == SS_STATUS_OK,
           "valid request is accepted");
    Expect(handle != SS_INVALID_AUDIO_REQUEST_HANDLE,
           "accepted request receives an opaque handle");
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_STARTED),
           "accepted request emits started");
    return handle;
}

std::uint32_t Submit(AudioEngine& engine,
                     const ss_audio_request_handle_t handle,
                     const std::vector<std::uint8_t>& pcm,
                     const std::vector<ss_audio_boundary_t>& boundaries = {})
{
    ss_audio_submit_result_t result{sizeof(result), 0, 99, 99};
    const auto status = engine.Submit(
        handle, pcm.empty() ? nullptr : pcm.data(), pcm.size(),
        boundaries.empty() ? nullptr : boundaries.data(),
        static_cast<std::uint32_t>(boundaries.size()), &result);
    if (status == SS_STATUS_OK) {
        Expect(result.accepted_frames == pcm.size() / 2,
               "successful submit accepts the complete slice");
    }
    return status;
}

void TestAbiAndCreateValidation()
{
    static_assert(SELECTSPEAK_NATIVE_API_VERSION == 8);
    static_assert(std::is_standard_layout_v<ss_audio_format_t>);
    static_assert(sizeof(ss_audio_format_t) == 16);
    static_assert(sizeof(ss_audio_boundary_t) == 16);
    static_assert(sizeof(ss_audio_submit_result_t) == 24);
    static_assert(sizeof(ss_audio_event_t) == 48);

    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    auto format = Format();
    ss_audio_request_handle_t handle = 99;
    Expect(engine.Create(0, &format, 10, Recorder::Callback, &recorder,
                         &handle) == SS_STATUS_INVALID_REQUEST,
           "request zero is rejected");
    Expect(handle == SS_INVALID_AUDIO_REQUEST_HANDLE,
           "rejected create clears the handle");
    format.channel_count = 2;
    Expect(engine.Create(1, &format, 10, Recorder::Callback, &recorder,
                         &handle) == SS_STATUS_INVALID_ARGUMENT,
           "first implementation rejects non-mono PCM");
    Expect(recorder.Snapshot().empty(), "rejected create emits no event");
}

void TestSignedPcmVolumeScaling()
{
    const std::int16_t samples[]{-20'000, -1'000, 0, 1'000, 20'000};
    std::vector<std::uint8_t> pcm(sizeof(samples));
    std::memcpy(pcm.data(), samples, sizeof(samples));
    selectspeak::audio::ScalePcm16(pcm, 20);

    std::int16_t scaled[std::size(samples)]{};
    std::memcpy(scaled, pcm.data(), pcm.size());
    Expect(scaled[0] == -4'000 && scaled[1] == -200 && scaled[2] == 0 &&
               scaled[3] == 200 && scaled[4] == 4'000,
           "volume scaling preserves signed PCM polarity without wrapping");
}

void TestPrebufferAndShortInput()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    const auto voice = sink->Voice();

    Expect(Submit(engine, handle, Pcm(10)) == SS_STATUS_OK,
           "short PCM is accepted");
    {
        std::lock_guard lock(voice->mutex);
        Expect(voice->starts == 0, "short input waits for finish before playback");
    }
    Expect(engine.FinishInput(handle) == SS_STATUS_OK,
           "short input finishes");
    {
        std::lock_guard lock(voice->mutex);
        Expect(voice->starts == 1, "finish starts input below prebuffer");
        Expect(voice->contexts.size() == 1 && voice->final_flags.front(),
               "short input submits one final buffer");
    }
    sink->EndNext(voice);
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_TERMINAL),
           "short input completes after playback");
    engine.Destroy(handle);

    Recorder prebuffer_recorder;
    const auto prebuffer_handle = Create(engine, prebuffer_recorder, 2);
    const auto prebuffer_voice = sink->Voice(1);
    Submit(engine, prebuffer_handle, Pcm(20));
    {
        std::lock_guard lock(prebuffer_voice->mutex);
        Expect(prebuffer_voice->starts == 0,
               "playback does not start below the 300ms prebuffer");
    }
    Submit(engine, prebuffer_handle, Pcm(20));
    {
        std::lock_guard lock(prebuffer_voice->mutex);
        Expect(prebuffer_voice->starts == 1,
               "playback starts once submitted PCM reaches prebuffer");
    }
    engine.Stop(prebuffer_handle, SS_TERMINAL_CANCELLED);
    engine.Destroy(prebuffer_handle);
}

void TestNativeProducerMustMatchRequestIdentity()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder, 41, 10);
    const auto pcm = Pcm(10);
    ss_audio_submit_result_t result{sizeof(result), 0, 0, 0};

    Expect(engine.SubmitForRequest(handle, 40, pcm.data(), pcm.size(),
                                   nullptr, 0, &result) ==
               SS_STATUS_INVALID_REQUEST,
           "native producer cannot feed a different request identity");
    Expect(engine.ValidateProducerTextRange(handle, 40, 0, 1) ==
               SS_STATUS_INVALID_REQUEST,
           "native text producer cannot claim a different request identity");
    Expect(engine.ValidateProducerTextRange(handle, 41, 19, 2) ==
               SS_STATUS_INVALID_BOUNDARY,
           "native text producer cannot exceed the complete request text");
    Expect(engine.ValidateProducerTextRange(handle, 41, 20, 0) ==
               SS_STATUS_OK,
           "native text producer accepts the complete-text end edge");
    Expect(engine.SubmitForRequest(handle, 41, pcm.data(), pcm.size(),
                                   nullptr, 0, &result) == SS_STATUS_OK,
           "matching native producer feeds the request-scoped handle");
    Expect(result.accepted_frames == 10,
           "native producer receives accepted-frame telemetry");
    engine.Stop(handle, SS_TERMINAL_CANCELLED);
    engine.Destroy(handle);
}

void TestBoundariesCompletionAndLatency()
{
    auto sink = std::make_shared<FakeSink>();
    sink->latency_frames = 10;
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    const auto voice = sink->Voice();

    const std::vector<ss_audio_boundary_t> first_boundaries{
        {10, 0, 1}, {10, 1, 1}, {20, 2, 1}};
    const std::vector<ss_audio_boundary_t> final_boundaries{{10, 3, 1}};
    Submit(engine, handle, Pcm(20), first_boundaries);
    Submit(engine, handle, Pcm(20));
    Submit(engine, handle, Pcm(10), final_boundaries);
    Expect(engine.FinishInput(handle) == SS_STATUS_OK,
           "boundary request finishes input");

    sink->Advance(voice, 19);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    auto before = recorder.Snapshot();
    Expect(std::count_if(before.begin(), before.end(), [](const auto& event) {
               return event.kind == SS_AUDIO_EVENT_PLAYED_WORD;
           }) == 0,
           "output latency delays boundaries");
    sink->Advance(voice, 20);
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_PLAYED_WORD, 2),
           "duplicate boundaries dispatch together in input order");
    for (int index = 0; index < 5; ++index) {
        sink->EndNext(voice);
    }
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_TERMINAL),
           "stream and buffer completion settle the request");

    const auto events = recorder.Snapshot();
    std::vector<std::uint32_t> positions;
    for (const auto& event : events) {
        if (event.kind == SS_AUDIO_EVENT_PLAYED_WORD) {
            positions.push_back(event.text_position);
        }
    }
    Expect(positions == std::vector<std::uint32_t>({0, 1, 2, 3}),
           "boundaries including the final frame remain ordered");
    Expect(events.back().kind == SS_AUDIO_EVENT_TERMINAL &&
               events.back().terminal_status == SS_TERMINAL_COMPLETED,
           "terminal completed is the final callback");
    engine.Destroy(handle);
}

void TestBoundaryRejectionIsAtomic()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    ss_audio_submit_result_t result{sizeof(result), 0, 7, 9};
    const auto pcm = Pcm(10);
    const ss_audio_boundary_t invalid[]{{8, 0, 1}, {7, 1, 1}};
    Expect(engine.Submit(handle, pcm.data(), pcm.size(), invalid, 2, &result) ==
               SS_STATUS_INVALID_BOUNDARY,
           "nonmonotonic boundaries reject the whole submission");
    Expect(result.accepted_frames == 0 && result.buffered_frames_after_submit == 0,
           "invalid boundary accepts no PCM or telemetry");
    const ss_audio_boundary_t outside[]{{11, 0, 1}};
    Expect(engine.Submit(handle, pcm.data(), pcm.size(), outside, 1, &result) ==
               SS_STATUS_INVALID_BOUNDARY,
           "boundary beyond the slice is rejected");
    engine.Stop(handle, SS_TERMINAL_CANCELLED);
    Expect(Submit(engine, handle, pcm) == SS_STATUS_WRONG_STATE,
           "submit after stop is rejected");
    engine.Destroy(handle);
    Expect(engine.Destroy(handle) == SS_STATUS_INVALID_HANDLE,
           "destroyed handles stay invalid");
}

void TestPauseResumeAndStopWhilePaused()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    const auto voice = sink->Voice();
    Submit(engine, handle, Pcm(20));
    Submit(engine, handle, Pcm(20));
    Submit(engine, handle, Pcm(20));
    Expect(engine.Pause(handle) == SS_STATUS_OK &&
               engine.Pause(handle) == SS_STATUS_OK,
           "pause is idempotent");
    Expect(engine.Resume(handle) == SS_STATUS_OK &&
               engine.Resume(handle) == SS_STATUS_OK,
           "resume is idempotent");
    Expect(engine.Pause(handle) == SS_STATUS_OK,
           "active playback pauses again");
    Expect(engine.Stop(handle, SS_TERMINAL_CANCELLED) == SS_STATUS_OK &&
               engine.Stop(handle, SS_TERMINAL_CANCELLED) == SS_STATUS_OK,
           "stop while paused is idempotent");
    const auto events = recorder.Snapshot();
    Expect(std::count_if(events.begin(), events.end(), [](const auto& event) {
               return event.kind == SS_AUDIO_EVENT_TERMINAL;
           }) == 1,
           "stop emits exactly one terminal");
    {
        std::lock_guard lock(voice->mutex);
        Expect(voice->destroys == 1, "stop destroys the request voice once");
    }
    engine.Destroy(handle);
}

void TestSupersedeUsesFreshVoiceAndRejectsStaleIds()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder first;
    const auto first_handle = Create(engine, first, 10);
    Submit(engine, first_handle, Pcm(20));

    Recorder second;
    const auto second_handle = Create(engine, second, 11);
    Expect(first.WaitForKind(SS_AUDIO_EVENT_TERMINAL),
           "replacement settles the old request");
    Expect(first.Snapshot().back().terminal_status == SS_TERMINAL_SUPERSEDED,
           "replacement uses superseded terminal status");
    Expect(sink->VoiceCount() == 2, "each accepted request gets a fresh voice");
    const auto old_voice = sink->Voice(0);
    {
        std::lock_guard lock(old_voice->mutex);
        Expect(old_voice->destroys == 1,
               "superseded request voice is destroyed");
    }
    auto format = Format();
    ss_audio_request_handle_t stale_handle = 0;
    Expect(engine.Create(10, &format, 20, Recorder::Callback, &second,
                         &stale_handle) == SS_STATUS_INVALID_REQUEST,
           "stale request ID is rejected");
    engine.Stop(second_handle, SS_TERMINAL_CANCELLED);
    engine.Destroy(first_handle);
    engine.Destroy(second_handle);
}

void TestBlockedSubmissionWakesOnStopAndClose()
{
    auto run = [](const bool close) {
        auto sink = std::make_shared<FakeSink>();
        AudioEngine engine(sink);
        Recorder recorder;
        const auto handle = Create(engine, recorder);
        Submit(engine, handle, Pcm(300));
        std::uint32_t status = SS_STATUS_INTERNAL_ERROR;
        std::thread producer([&] { status = Submit(engine, handle, Pcm(200)); });
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        if (close) {
            Expect(engine.Destroy(handle) == SS_STATUS_OK,
                   "close destroys a capacity-blocked request");
        } else {
            Expect(engine.Stop(handle, SS_TERMINAL_CANCELLED) == SS_STATUS_OK,
                   "stop settles a capacity-blocked request");
        }
        producer.join();
        Expect(status == (close ? SS_STATUS_CLOSED : SS_STATUS_WRONG_STATE),
               "blocked submit wakes with the request's interruption status");
        if (!close) {
            engine.Destroy(handle);
        }
    };
    run(false);
    run(true);
}

void TestBoundedAdmissionResumesAtLowWater()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    const auto voice = sink->Voice();
    Submit(engine, handle, Pcm(300));

    std::atomic<bool> finished{false};
    std::uint32_t status = SS_STATUS_INTERNAL_ERROR;
    std::thread producer([&] {
        status = Submit(engine, handle, Pcm(300));
        finished.store(true, std::memory_order_release);
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
    for (int index = 0; index < 20; ++index) {
        sink->EndNext(voice);
    }
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::seconds(2);
    while (!finished.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (!finished.load(std::memory_order_acquire)) {
        engine.Stop(handle, SS_TERMINAL_CANCELLED);
    }
    producer.join();
    Expect(status == SS_STATUS_OK,
           "bounded submit resumes when buffered audio reaches low water");
    engine.Stop(handle, SS_TERMINAL_CANCELLED);
    engine.Destroy(handle);
}

void TestUnderrunStartAndRecovery()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    const auto voice = sink->Voice();
    Submit(engine, handle, Pcm(30));
    Submit(engine, handle, Pcm(1));
    sink->EndNext(voice);
    sink->EndNext(voice);
    sink->EndNext(voice);
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_UNDERRUN),
           "empty active source queue reports underrun start");
    Submit(engine, handle, Pcm(1));
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_UNDERRUN, 2),
           "newly queued PCM reports underrun recovery");
    const auto events = recorder.Snapshot();
    std::vector<std::uint64_t> runway;
    for (const auto& event : events) {
        if (event.kind == SS_AUDIO_EVENT_UNDERRUN) {
            runway.push_back(event.buffered_frames);
        }
    }
    Expect(runway.size() >= 2 && runway[0] == 0 && runway[1] > 0,
           "underrun start and recovery carry distinct runway values");
    engine.Stop(handle, SS_TERMINAL_CANCELLED);
    engine.Destroy(handle);
}

void TestVoiceFailureAndCloseQuiescence()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    const auto voice = sink->Voice();
    Submit(engine, handle, Pcm(30));
    Submit(engine, handle, Pcm(1));
    sink->FailVoice(voice);
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_TERMINAL),
           "voice failure settles the request");
    const auto failed_events = recorder.Snapshot();
    Expect(failed_events.back().terminal_status == SS_TERMINAL_FAILED &&
               failed_events.back().status == SS_STATUS_DEVICE_ERROR &&
               !failed_events.back().diagnostic.empty(),
           "voice failure is request-local and diagnostic");
    engine.Destroy(handle);
    const auto count_after_close = recorder.Snapshot().size();
    sink->Advance(voice, 1000);
    sink->EndNext(voice);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    Expect(recorder.Snapshot().size() == count_after_close,
           "no callback occurs after destroy returns");
}

void TestVoiceFailureBeforePlaybackStarts()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    Recorder recorder;
    const auto handle = Create(engine, recorder);
    sink->FailVoice(sink->Voice());
    Expect(recorder.WaitForKind(SS_AUDIO_EVENT_TERMINAL),
           "device failure before prebuffer settles the request");
    Expect(recorder.Snapshot().back().terminal_status == SS_TERMINAL_FAILED,
           "pre-start device failure emits failed");
    engine.Destroy(handle);
}

struct ReentrantContext {
    AudioEngine* engine = nullptr;
    Recorder recorder;
    ss_audio_request_handle_t handle = 0;
    std::uint32_t pause_status = SS_STATUS_INTERNAL_ERROR;
};

void __cdecl ReentrantCallback(const ss_audio_event_t* const event,
                               void* const raw_context)
{
    auto& context = *static_cast<ReentrantContext*>(raw_context);
    if (event != nullptr && event->kind == SS_AUDIO_EVENT_PLAYED_WORD) {
        context.pause_status = context.engine->Pause(context.handle);
    }
    Recorder::Callback(event, &context.recorder);
}

void TestCallbacksRunWithoutNativeLocks()
{
    auto sink = std::make_shared<FakeSink>();
    AudioEngine engine(sink);
    ReentrantContext context{};
    context.engine = &engine;
    auto format = Format();
    Expect(engine.Create(1, &format, 20, ReentrantCallback, &context,
                         &context.handle) == SS_STATUS_OK,
           "reentrant callback request is accepted");
    Expect(context.recorder.WaitForKind(SS_AUDIO_EVENT_STARTED),
           "reentrant request starts");
    const std::vector<ss_audio_boundary_t> boundaries{{1, 0, 1}};
    Submit(engine, context.handle, Pcm(30), boundaries);
    Submit(engine, context.handle, Pcm(1));
    sink->Advance(sink->Voice(), 1);
    Expect(context.recorder.WaitForKind(SS_AUDIO_EVENT_PLAYED_WORD),
           "played word callback runs");
    Expect(context.pause_status == SS_STATUS_WRONG_STATE,
           "same-handle callback reentry is rejected without deadlock");
    engine.Stop(context.handle, SS_TERMINAL_CANCELLED);
    engine.Destroy(context.handle);
}

void TestShutdownClosesPlayback()
{
    auto sink = std::make_shared<FakeSink>();
    Recorder recorder;
    {
        AudioEngine engine(sink);
        const auto handle = Create(engine, recorder);
        Submit(engine, handle, Pcm(30));
        engine.Shutdown();
        Expect(recorder.WaitForKind(SS_AUDIO_EVENT_TERMINAL),
               "engine shutdown closes active playback");
        Expect(recorder.Snapshot().back().terminal_status == SS_TERMINAL_CLOSED,
               "shutdown terminal is closed");
    }
    Expect(sink->shutdown, "engine shutdown releases the persistent sink");
}

}  // namespace

int main()
{
    TestAbiAndCreateValidation();
    TestSignedPcmVolumeScaling();
    TestPrebufferAndShortInput();
    TestNativeProducerMustMatchRequestIdentity();
    TestBoundariesCompletionAndLatency();
    TestBoundaryRejectionIsAtomic();
    TestPauseResumeAndStopWhilePaused();
    TestSupersedeUsesFreshVoiceAndRejectsStaleIds();
    TestBlockedSubmissionWakesOnStopAndClose();
    TestBoundedAdmissionResumesAtLowWater();
    TestUnderrunStartAndRecovery();
    TestVoiceFailureAndCloseQuiescence();
    TestVoiceFailureBeforePlaybackStarts();
    TestCallbacksRunWithoutNativeLocks();
    TestShutdownClosesPlayback();

    if (failures == 0) {
        std::cout << "audio request engine checks passed\n";
    }
    return failures == 0 ? 0 : 1;
}
