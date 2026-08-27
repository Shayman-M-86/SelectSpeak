#include "audio_engine.h"

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstring>
#include <deque>
#include <limits>
#include <list>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace selectspeak::audio {
namespace {

constexpr std::uint64_t kPrebufferMilliseconds = 300;

struct QueuedBuffer {
    std::vector<std::uint8_t> pcm;
    std::uint64_t frame_count = 0;
    std::atomic<bool> ended{false};
};

struct AbsoluteBoundary {
    std::uint64_t frame_offset = 0;
    std::uint32_t text_position = 0;
    std::uint32_t text_length = 0;
};

struct PendingEvent {
    std::uint32_t kind = 0;
    std::uint32_t terminal_status = SS_TERMINAL_NONE;
    std::uint32_t status = SS_STATUS_OK;
    std::uint32_t text_position = 0;
    std::uint32_t text_length = 0;
    std::uint64_t buffered_frames = 0;
    std::string diagnostic;
};

class AudioRequest final : public VoiceNotifications {
public:
    AudioRequest(const std::uint64_t request_id,
                 const ss_audio_format_t& format,
                 const std::uint32_t request_text_length_utf16,
                 const ss_audio_event_callback_t callback, void* const context,
                 std::shared_ptr<AudioSink> sink)
        : request_id_(request_id),
          format_(format),
          request_text_length_utf16_(request_text_length_utf16),
          callback_(callback),
          context_(context),
          sink_(std::move(sink)),
          low_water_frames_(format.sample_rate_hz),
          high_water_frames_(
              static_cast<std::uint64_t>(format.sample_rate_hz) * 3),
          hard_capacity_frames_(static_cast<std::uint64_t>(format.sample_rate_hz) * 4),
          prebuffer_frames_(std::max<std::uint64_t>(
              1, static_cast<std::uint64_t>(format.sample_rate_hz) *
                     kPrebufferMilliseconds / 1000))
    {
    }

    ~AudioRequest() override
    {
        Destroy();
    }

    std::uint64_t RequestId() const noexcept { return request_id_; }
    std::uint32_t RequestTextLength() const noexcept
    {
        return request_text_length_utf16_;
    }

    bool Initialize()
    {
        voice_ = sink_->CreateVoice(format_, *this);
        if (!voice_) {
            return false;
        }
        dispatcher_ = std::thread(&AudioRequest::DispatchLoop, this);
        dispatcher_id_ = dispatcher_.get_id();
        {
            std::lock_guard lock(mutex_);
            EnqueueEventLocked(PendingEvent{SS_AUDIO_EVENT_STARTED});
        }
        activity_.notify_all();
        return true;
    }

    bool OnDispatcherThread() const noexcept
    {
        return dispatcher_id_ == std::this_thread::get_id();
    }

    std::uint32_t Submit(const void* const pcm,
                         const std::uint64_t pcm_byte_length,
                         const ss_audio_boundary_t* const boundaries,
                         const std::uint32_t boundary_count,
                         ss_audio_submit_result_t* const result)
    {
        if (OnDispatcherThread()) {
            return SS_STATUS_WRONG_STATE;
        }
        if (result == nullptr || result->size != sizeof(ss_audio_submit_result_t)) {
            return SS_STATUS_INVALID_ARGUMENT;
        }
        result->accepted_frames = 0;
        result->buffered_frames_after_submit = 0;

        const std::uint64_t bytes_per_frame =
            static_cast<std::uint64_t>(format_.channel_count) * sizeof(std::int16_t);
        if ((pcm_byte_length != 0 && pcm == nullptr) ||
            pcm_byte_length % bytes_per_frame != 0 ||
            pcm_byte_length > std::numeric_limits<std::uint32_t>::max() ||
            (boundary_count != 0 && boundaries == nullptr)) {
            return SS_STATUS_INVALID_ARGUMENT;
        }
        const std::uint64_t frame_count = pcm_byte_length / bytes_per_frame;
        const auto boundary_status = ValidateBoundaries(
            boundaries, boundary_count, frame_count, request_text_length_utf16_);
        if (boundary_status != SS_STATUS_OK) {
            return boundary_status;
        }
        if (frame_count == 0) {
            std::lock_guard lock(mutex_);
            if (!accepting_ || terminal_ || destroying_) {
                return terminal_status_ == SS_TERMINAL_CLOSED ? SS_STATUS_CLOSED
                                                              : SS_STATUS_WRONG_STATE;
            }
            result->buffered_frames_after_submit = buffered_frames_;
            return SS_STATUS_OK;
        }
        if (frame_count > hard_capacity_frames_) {
            return SS_STATUS_INVALID_ARGUMENT;
        }

        std::vector<std::uint8_t> pcm_copy(static_cast<std::size_t>(pcm_byte_length));
        std::memcpy(pcm_copy.data(), pcm, pcm_copy.size());
        std::vector<ss_audio_boundary_t> boundary_copy;
        if (boundary_count != 0) {
            boundary_copy.assign(boundaries, boundaries + boundary_count);
        }

        std::unique_lock lock(mutex_);
        if (pending_) {
            if (!SubmitPendingLocked(false)) {
                lock.unlock();
                Fail(SS_STATUS_DEVICE_ERROR, "XAudio2 rejected a PCM buffer");
                return SS_STATUS_DEVICE_ERROR;
            }
            MaybeStartLocked();
        }
        const bool capacity_blocked =
            buffered_frames_ >= high_water_frames_ ||
            buffered_frames_ + frame_count > hard_capacity_frames_;
        capacity_.wait(lock, [&] {
            if (!accepting_ || terminal_ || destroying_) {
                return true;
            }
            if (capacity_blocked) {
                return buffered_frames_ <= low_water_frames_ &&
                       buffered_frames_ + frame_count <= hard_capacity_frames_;
            }
            return buffered_frames_ + frame_count <= hard_capacity_frames_;
        });
        if (!accepting_ || terminal_ || destroying_) {
            return InterruptionStatusLocked();
        }

        const std::uint64_t submission_base = accepted_frames_;
        if (!QueueSubmissionLocked(std::move(pcm_copy), frame_count)) {
            lock.unlock();
            Fail(SS_STATUS_DEVICE_ERROR, "XAudio2 rejected a PCM buffer");
            return SS_STATUS_DEVICE_ERROR;
        }
        for (const auto& boundary : boundary_copy) {
            boundaries_.push_back(AbsoluteBoundary{
                submission_base + boundary.frame_offset,
                boundary.text_position,
                boundary.text_length,
            });
        }
        accepted_frames_ += frame_count;
        buffered_frames_ += frame_count;
        MaybeStartLocked();
        result->accepted_frames = frame_count;
        result->buffered_frames_after_submit = buffered_frames_;
        state_changes_.fetch_add(1, std::memory_order_relaxed);
        activity_.notify_all();
        return SS_STATUS_OK;
    }

    std::uint32_t FinishInput()
    {
        if (OnDispatcherThread()) {
            return SS_STATUS_WRONG_STATE;
        }
        std::unique_lock lock(mutex_);
        if (terminal_ || destroying_) {
            return SS_STATUS_WRONG_STATE;
        }
        if (!accepting_) {
            return SS_STATUS_WRONG_STATE;
        }
        accepting_ = false;
        input_finished_ = true;
        if (pending_ && !SubmitPendingLocked(true)) {
            lock.unlock();
            Fail(SS_STATUS_DEVICE_ERROR, "XAudio2 rejected the final PCM buffer");
            return SS_STATUS_DEVICE_ERROR;
        }
        if (submitted_buffers_.empty()) {
            CompleteWithoutAudioLocked();
        } else if (!StartVoiceLocked()) {
            lock.unlock();
            Fail(SS_STATUS_DEVICE_ERROR, "XAudio2 could not start playback");
            return SS_STATUS_DEVICE_ERROR;
        }
        activity_.notify_all();
        capacity_.notify_all();
        return SS_STATUS_OK;
    }

    std::uint32_t Pause()
    {
        if (OnDispatcherThread()) {
            return SS_STATUS_WRONG_STATE;
        }
        std::unique_lock lock(mutex_);
        if (terminal_ || destroying_) {
            return SS_STATUS_WRONG_STATE;
        }
        if (paused_) {
            return SS_STATUS_OK;
        }
        if (voice_started_ && !voice_->Pause()) {
            lock.unlock();
            Fail(SS_STATUS_DEVICE_ERROR, "XAudio2 could not pause playback");
            return SS_STATUS_DEVICE_ERROR;
        }
        paused_ = true;
        return SS_STATUS_OK;
    }

    std::uint32_t Resume()
    {
        if (OnDispatcherThread()) {
            return SS_STATUS_WRONG_STATE;
        }
        std::unique_lock lock(mutex_);
        if (terminal_ || destroying_) {
            return SS_STATUS_WRONG_STATE;
        }
        if (!paused_) {
            return SS_STATUS_OK;
        }
        paused_ = false;
        const bool should_start = voice_started_ || input_finished_ ||
                                  submitted_frames_ >= prebuffer_frames_;
        if (should_start && !StartOrResumeVoiceLocked()) {
            lock.unlock();
            Fail(SS_STATUS_DEVICE_ERROR, "XAudio2 could not resume playback");
            return SS_STATUS_DEVICE_ERROR;
        }
        return SS_STATUS_OK;
    }

    std::uint32_t Stop(const std::uint32_t terminal_reason)
    {
        if (OnDispatcherThread()) {
            return SS_STATUS_WRONG_STATE;
        }
        if (!IsStopReason(terminal_reason)) {
            return SS_STATUS_INVALID_ARGUMENT;
        }
        {
            std::unique_lock lock(mutex_);
            if (terminal_) {
                return SS_STATUS_OK;
            }
            accepting_ = false;
            input_finished_ = true;
            DestroyVoiceLocked();
            pending_.reset();
            submitted_buffers_.clear();
            boundaries_.clear();
            buffered_frames_ = 0;
            SetTerminalLocked(terminal_reason, SS_STATUS_OK, {});
        }
        capacity_.notify_all();
        activity_.notify_all();
        WaitForTerminalDelivery();
        return SS_STATUS_OK;
    }

    void Destroy()
    {
        std::thread dispatcher;
        {
            std::unique_lock lock(mutex_);
            if (destroyed_) {
                return;
            }
            if (!terminal_) {
                accepting_ = false;
                input_finished_ = true;
                DestroyVoiceLocked();
                pending_.reset();
                submitted_buffers_.clear();
                boundaries_.clear();
                buffered_frames_ = 0;
                SetTerminalLocked(SS_TERMINAL_CLOSED, SS_STATUS_OK, {});
            }
            destroying_ = true;
            dispatcher = std::move(dispatcher_);
        }
        capacity_.notify_all();
        activity_.notify_all();
        if (dispatcher.joinable() && dispatcher.get_id() != std::this_thread::get_id()) {
            dispatcher.join();
        }
        std::lock_guard lock(mutex_);
        DestroyVoiceLocked();
        pending_.reset();
        submitted_buffers_.clear();
        boundaries_.clear();
        events_.clear();
        destroyed_ = true;
    }

    void OnBufferEnd(void* const context) noexcept override
    {
        if (context != nullptr) {
            static_cast<QueuedBuffer*>(context)->ended.store(
                true, std::memory_order_release);
        }
        activity_.notify_all();
    }

    void OnStreamEnd() noexcept override
    {
        stream_ends_.fetch_add(1, std::memory_order_relaxed);
        activity_.notify_all();
    }

    void OnProcessingPassEnd() noexcept override
    {
        processing_passes_.fetch_add(1, std::memory_order_relaxed);
        activity_.notify_all();
    }

    void OnVoiceError(const std::uint32_t status) noexcept override
    {
        voice_error_.store(status == SS_STATUS_OK ? SS_STATUS_DEVICE_ERROR : status,
                           std::memory_order_relaxed);
        activity_.notify_all();
    }

private:
    static std::uint32_t ValidateBoundaries(
        const ss_audio_boundary_t* const boundaries,
        const std::uint32_t count, const std::uint64_t frame_count,
        const std::uint32_t text_length)
    {
        std::uint64_t previous_frame = 0;
        for (std::uint32_t index = 0; index < count; ++index) {
            const auto& boundary = boundaries[index];
            if ((index != 0 && boundary.frame_offset < previous_frame) ||
                boundary.frame_offset > frame_count ||
                boundary.text_length == 0 ||
                boundary.text_position > text_length ||
                boundary.text_length > text_length - boundary.text_position) {
                return SS_STATUS_INVALID_BOUNDARY;
            }
            previous_frame = boundary.frame_offset;
        }
        return SS_STATUS_OK;
    }

    static bool IsStopReason(const std::uint32_t reason)
    {
        return reason == SS_TERMINAL_CANCELLED ||
               reason == SS_TERMINAL_SUPERSEDED ||
               reason == SS_TERMINAL_FAILED || reason == SS_TERMINAL_CLOSED;
    }

    std::uint32_t InterruptionStatusLocked() const
    {
        if (terminal_status_ == SS_TERMINAL_CLOSED || destroying_) {
            return SS_STATUS_CLOSED;
        }
        if (terminal_status_ == SS_TERMINAL_FAILED) {
            return terminal_error_ == SS_STATUS_OK ? SS_STATUS_DEVICE_ERROR
                                                   : terminal_error_;
        }
        return SS_STATUS_WRONG_STATE;
    }

    bool SubmitPendingLocked(const bool end_of_stream)
    {
        auto buffer = std::move(pending_);
        QueuedBuffer* const context = buffer.get();
        if (!voice_->Submit(buffer->pcm.data(),
                            static_cast<std::uint32_t>(buffer->pcm.size()),
                            context, end_of_stream)) {
            pending_ = std::move(buffer);
            return false;
        }
        submitted_frames_ += buffer->frame_count;
        submitted_buffers_.push_back(std::move(buffer));
        return true;
    }

    bool QueueSubmissionLocked(std::vector<std::uint8_t> pcm,
                               const std::uint64_t frame_count)
    {
        const std::uint64_t bytes_per_frame =
            static_cast<std::uint64_t>(format_.channel_count) *
            sizeof(std::int16_t);
        const std::uint64_t chunk_frames =
            std::max<std::uint64_t>(1, format_.sample_rate_hz / 10);
        std::uint64_t frame_offset = 0;
        while (frame_offset < frame_count) {
            const std::uint64_t frames =
                std::min(chunk_frames, frame_count - frame_offset);
            const std::uint64_t byte_offset = frame_offset * bytes_per_frame;
            const std::uint64_t byte_count = frames * bytes_per_frame;
            auto buffer = std::make_unique<QueuedBuffer>();
            buffer->pcm.assign(
                pcm.begin() + static_cast<std::ptrdiff_t>(byte_offset),
                pcm.begin() + static_cast<std::ptrdiff_t>(byte_offset +
                                                          byte_count));
            buffer->frame_count = frames;
            if (frame_offset + frames == frame_count) {
                pending_ = std::move(buffer);
            } else {
                QueuedBuffer* const context = buffer.get();
                if (!voice_->Submit(
                        buffer->pcm.data(),
                        static_cast<std::uint32_t>(buffer->pcm.size()),
                        context, false)) {
                    return false;
                }
                submitted_frames_ += frames;
                submitted_buffers_.push_back(std::move(buffer));
            }
            frame_offset += frames;
        }
        return true;
    }

    bool StartVoiceLocked()
    {
        if (paused_ || voice_started_ || submitted_buffers_.empty()) {
            return true;
        }
        if (!voice_->Start()) {
            return false;
        }
        voice_started_ = true;
        return true;
    }

    bool StartOrResumeVoiceLocked()
    {
        if (paused_ || !voice_) {
            return true;
        }
        if (!voice_->Start()) {
            return false;
        }
        voice_started_ = true;
        return true;
    }

    void MaybeStartLocked()
    {
        if (submitted_frames_ >= prebuffer_frames_ && !StartVoiceLocked()) {
            voice_error_.store(SS_STATUS_DEVICE_ERROR, std::memory_order_relaxed);
            activity_.notify_all();
        }
    }

    void CompleteWithoutAudioLocked()
    {
        DestroyVoiceLocked();
        SetTerminalLocked(SS_TERMINAL_COMPLETED, SS_STATUS_OK, {});
    }

    void DestroyVoiceLocked()
    {
        if (voice_) {
            voice_->Destroy();
            voice_.reset();
        }
    }

    void Fail(const std::uint32_t status, std::string diagnostic)
    {
        {
            std::lock_guard lock(mutex_);
            if (terminal_) {
                return;
            }
            accepting_ = false;
            input_finished_ = true;
            DestroyVoiceLocked();
            pending_.reset();
            submitted_buffers_.clear();
            boundaries_.clear();
            buffered_frames_ = 0;
            SetTerminalLocked(SS_TERMINAL_FAILED, status, std::move(diagnostic));
        }
        capacity_.notify_all();
        activity_.notify_all();
    }

    void SetTerminalLocked(const std::uint32_t terminal_status,
                           const std::uint32_t status,
                           std::string diagnostic)
    {
        if (terminal_) {
            return;
        }
        terminal_ = true;
        terminal_status_ = terminal_status;
        terminal_error_ = status;
        PendingEvent event{};
        event.kind = SS_AUDIO_EVENT_TERMINAL;
        event.terminal_status = terminal_status;
        event.status = status;
        event.diagnostic = std::move(diagnostic);
        EnqueueEventLocked(std::move(event));
    }

    void EnqueueEventLocked(PendingEvent event)
    {
        events_.push_back(std::move(event));
    }

    void ReclaimEndedBuffersLocked()
    {
        for (auto iterator = submitted_buffers_.begin();
             iterator != submitted_buffers_.end();) {
            if (!(*iterator)->ended.load(std::memory_order_acquire)) {
                ++iterator;
                continue;
            }
            buffered_frames_ -= (*iterator)->frame_count;
            iterator = submitted_buffers_.erase(iterator);
            capacity_.notify_all();
        }
    }

    void ObservePlaybackLocked()
    {
        if (terminal_) {
            return;
        }
        const auto voice_error = voice_error_.exchange(SS_STATUS_OK);
        if (voice_error != SS_STATUS_OK) {
            accepting_ = false;
            input_finished_ = true;
            DestroyVoiceLocked();
            pending_.reset();
            submitted_buffers_.clear();
            boundaries_.clear();
            buffered_frames_ = 0;
            SetTerminalLocked(SS_TERMINAL_FAILED, voice_error,
                              "XAudio2 reported a voice or device failure");
            capacity_.notify_all();
            return;
        }
        if (!voice_ || !voice_started_) {
            return;
        }

        VoiceState state{};
        if (!voice_->GetState(state)) {
            voice_error_.store(SS_STATUS_DEVICE_ERROR);
            return;
        }
        const std::uint64_t latency =
            sink_->OutputLatencyFrames(format_.sample_rate_hz);
        const std::uint64_t audible_frames =
            state.samples_played > latency ? state.samples_played - latency : 0;
        while (!boundaries_.empty() &&
               boundaries_.front().frame_offset <= audible_frames) {
            const auto boundary = boundaries_.front();
            boundaries_.pop_front();
            PendingEvent event{};
            event.kind = SS_AUDIO_EVENT_PLAYED_WORD;
            event.text_position = boundary.text_position;
            event.text_length = boundary.text_length;
            EnqueueEventLocked(std::move(event));
        }

        const bool underrun_now = accepting_ && !paused_ &&
                                  state.buffers_queued == 0;
        if (underrun_now != underrun_) {
            underrun_ = underrun_now;
            PendingEvent event{};
            event.kind = SS_AUDIO_EVENT_UNDERRUN;
            event.buffered_frames = underrun_now ? 0 : buffered_frames_;
            EnqueueEventLocked(std::move(event));
        }
    }

    void CompleteIfReadyLocked()
    {
        if (terminal_ || !input_finished_ || pending_) {
            return;
        }
        if (!submitted_buffers_.empty() ||
            stream_ends_.load(std::memory_order_relaxed) == 0) {
            return;
        }
        while (!boundaries_.empty()) {
            const auto boundary = boundaries_.front();
            boundaries_.pop_front();
            PendingEvent event{};
            event.kind = SS_AUDIO_EVENT_PLAYED_WORD;
            event.text_position = boundary.text_position;
            event.text_length = boundary.text_length;
            EnqueueEventLocked(std::move(event));
        }
        DestroyVoiceLocked();
        SetTerminalLocked(SS_TERMINAL_COMPLETED, SS_STATUS_OK, {});
    }

    void DispatchLoop()
    {
        for (;;) {
            std::deque<PendingEvent> events;
            {
                std::unique_lock lock(mutex_);
                activity_.wait(lock, [&] {
                    return destroying_ || !events_.empty() ||
                           voice_error_.load(std::memory_order_relaxed) != SS_STATUS_OK ||
                           stream_ends_.load(std::memory_order_relaxed) != observed_stream_ends_ ||
                           processing_passes_.load(std::memory_order_relaxed) !=
                               observed_processing_passes_ ||
                           state_changes_.load(std::memory_order_relaxed) !=
                               observed_state_changes_ ||
                           AnyBufferEndedLocked();
                });
                ReclaimEndedBuffersLocked();
                observed_stream_ends_ = stream_ends_.load(std::memory_order_relaxed);
                observed_processing_passes_ =
                    processing_passes_.load(std::memory_order_relaxed);
                observed_state_changes_ =
                    state_changes_.load(std::memory_order_relaxed);
                ObservePlaybackLocked();
                CompleteIfReadyLocked();
                events.swap(events_);
                if (destroying_ && events.empty()) {
                    break;
                }
            }
            for (const auto& event : events) {
                Deliver(event);
            }
        }
    }

    bool AnyBufferEndedLocked() const
    {
        return std::any_of(
            submitted_buffers_.begin(), submitted_buffers_.end(),
            [](const auto& buffer) {
                return buffer->ended.load(std::memory_order_acquire);
            });
    }

    void Deliver(const PendingEvent& pending)
    {
        ss_audio_event_t event{};
        event.size = sizeof(event);
        event.kind = pending.kind;
        event.request_id = request_id_;
        event.terminal_status = pending.terminal_status;
        event.status = pending.status;
        event.text_position = pending.text_position;
        event.text_length = pending.text_length;
        event.buffered_frames = pending.buffered_frames;
        event.diagnostic = pending.diagnostic.empty()
                               ? nullptr
                               : pending.diagnostic.c_str();
        callback_(&event, context_);
        if (pending.kind == SS_AUDIO_EVENT_TERMINAL) {
            std::lock_guard lock(mutex_);
            terminal_delivered_ = true;
            delivery_.notify_all();
        }
    }

    void WaitForTerminalDelivery()
    {
        std::unique_lock lock(mutex_);
        delivery_.wait(lock, [&] { return terminal_delivered_ || destroyed_; });
    }

    const std::uint64_t request_id_;
    const ss_audio_format_t format_;
    const std::uint32_t request_text_length_utf16_;
    const ss_audio_event_callback_t callback_;
    void* const context_;
    const std::shared_ptr<AudioSink> sink_;
    const std::uint64_t low_water_frames_;
    const std::uint64_t high_water_frames_;
    const std::uint64_t hard_capacity_frames_;
    const std::uint64_t prebuffer_frames_;

    std::mutex mutex_;
    std::condition_variable activity_;
    std::condition_variable capacity_;
    std::condition_variable delivery_;
    std::thread dispatcher_;
    std::thread::id dispatcher_id_{};
    std::unique_ptr<AudioVoice> voice_;
    std::unique_ptr<QueuedBuffer> pending_;
    std::list<std::unique_ptr<QueuedBuffer>> submitted_buffers_;
    std::deque<AbsoluteBoundary> boundaries_;
    std::deque<PendingEvent> events_;
    std::uint64_t accepted_frames_ = 0;
    std::uint64_t submitted_frames_ = 0;
    std::uint64_t buffered_frames_ = 0;
    std::uint64_t observed_stream_ends_ = 0;
    std::uint64_t observed_processing_passes_ = 0;
    std::uint64_t observed_state_changes_ = 0;
    std::atomic<std::uint64_t> stream_ends_{0};
    std::atomic<std::uint64_t> processing_passes_{0};
    std::atomic<std::uint64_t> state_changes_{0};
    std::atomic<std::uint32_t> voice_error_{SS_STATUS_OK};
    std::uint32_t terminal_status_ = SS_TERMINAL_NONE;
    std::uint32_t terminal_error_ = SS_STATUS_OK;
    bool accepting_ = true;
    bool input_finished_ = false;
    bool voice_started_ = false;
    bool paused_ = false;
    bool underrun_ = false;
    bool terminal_ = false;
    bool terminal_delivered_ = false;
    bool destroying_ = false;
    bool destroyed_ = false;
};

}  // namespace

class AudioEngine::Impl final {
public:
    explicit Impl(std::shared_ptr<AudioSink> sink) : sink_(std::move(sink)) {}

    std::shared_ptr<AudioRequest> Find(const ss_audio_request_handle_t handle)
    {
        std::lock_guard lock(mutex_);
        const auto found = requests_.find(handle);
        return found == requests_.end() ? nullptr : found->second;
    }

    std::mutex mutex_;
    std::mutex create_mutex_;
    std::shared_ptr<AudioSink> sink_;
    std::map<ss_audio_request_handle_t, std::shared_ptr<AudioRequest>> requests_;
    std::weak_ptr<AudioRequest> current_;
    ss_audio_request_handle_t next_handle_ = 1;
    std::uint64_t last_request_id_ = 0;
    bool closed_ = false;
};

AudioEngine::AudioEngine(std::shared_ptr<AudioSink> sink)
    : impl_(std::make_unique<Impl>(std::move(sink)))
{
}

AudioEngine::~AudioEngine()
{
    Shutdown();
}

std::uint32_t AudioEngine::Create(
    const std::uint64_t request_id, const ss_audio_format_t* const format,
    const std::uint32_t request_text_length_utf16,
    const ss_audio_event_callback_t callback, void* const context,
    ss_audio_request_handle_t* const handle)
{
    std::lock_guard create_lock(impl_->create_mutex_);
    if (handle == nullptr) {
        return SS_STATUS_INVALID_ARGUMENT;
    }
    *handle = SS_INVALID_AUDIO_REQUEST_HANDLE;
    if (request_id == 0) {
        return SS_STATUS_INVALID_REQUEST;
    }
    if (format == nullptr || format->size != sizeof(ss_audio_format_t) ||
        format->sample_rate_hz == 0 || format->channel_count != 1 ||
        format->sample_format != SS_SAMPLE_FORMAT_PCM_S16_LE ||
        callback == nullptr) {
        return SS_STATUS_INVALID_ARGUMENT;
    }

    std::shared_ptr<AudioRequest> old_request;
    {
        std::lock_guard lock(impl_->mutex_);
        if (impl_->closed_) {
            return SS_STATUS_CLOSED;
        }
        if (!impl_->sink_) {
            return SS_STATUS_DEVICE_ERROR;
        }
        if (request_id <= impl_->last_request_id_) {
            return SS_STATUS_INVALID_REQUEST;
        }
        old_request = impl_->current_.lock();
    }
    if (old_request) {
        old_request->Stop(SS_TERMINAL_SUPERSEDED);
    }

    auto request = std::make_shared<AudioRequest>(
        request_id, *format, request_text_length_utf16, callback, context,
        impl_->sink_);
    if (!request->Initialize()) {
        return SS_STATUS_DEVICE_ERROR;
    }

    {
        std::lock_guard lock(impl_->mutex_);
        if (impl_->closed_) {
            request->Destroy();
            return SS_STATUS_CLOSED;
        }
        const auto new_handle = impl_->next_handle_++;
        impl_->requests_.emplace(new_handle, request);
        impl_->current_ = request;
        impl_->last_request_id_ = request_id;
        *handle = new_handle;
    }
    return SS_STATUS_OK;
}

std::uint32_t AudioEngine::Submit(
    const ss_audio_request_handle_t handle, const void* const pcm,
    const std::uint64_t pcm_byte_length,
    const ss_audio_boundary_t* const boundaries,
    const std::uint32_t boundary_count,
    ss_audio_submit_result_t* const result)
{
    const auto request = impl_->Find(handle);
    return request ? request->Submit(pcm, pcm_byte_length, boundaries,
                                     boundary_count, result)
                   : SS_STATUS_INVALID_HANDLE;
}

std::uint32_t AudioEngine::SubmitForRequest(
    const ss_audio_request_handle_t handle, const std::uint64_t request_id,
    const void* const pcm, const std::uint64_t pcm_byte_length,
    const ss_audio_boundary_t* const boundaries,
    const std::uint32_t boundary_count,
    ss_audio_submit_result_t* const result)
{
    const auto request = impl_->Find(handle);
    if (!request) {
        return SS_STATUS_INVALID_HANDLE;
    }
    if (request_id == 0 || request->RequestId() != request_id) {
        return SS_STATUS_INVALID_REQUEST;
    }
    return request->Submit(pcm, pcm_byte_length, boundaries, boundary_count,
                           result);
}

std::uint32_t AudioEngine::ValidateProducerTextRange(
    const ss_audio_request_handle_t handle, const std::uint64_t request_id,
    const std::uint32_t text_position_utf16,
    const std::uint32_t text_length_utf16)
{
    const auto request = impl_->Find(handle);
    if (!request) {
        return SS_STATUS_INVALID_HANDLE;
    }
    if (request_id == 0 || request->RequestId() != request_id) {
        return SS_STATUS_INVALID_REQUEST;
    }
    const auto request_length = request->RequestTextLength();
    if (text_position_utf16 > request_length ||
        text_length_utf16 > request_length - text_position_utf16) {
        return SS_STATUS_INVALID_BOUNDARY;
    }
    return SS_STATUS_OK;
}

std::uint32_t AudioEngine::FinishInput(const ss_audio_request_handle_t handle)
{
    const auto request = impl_->Find(handle);
    return request ? request->FinishInput() : SS_STATUS_INVALID_HANDLE;
}

std::uint32_t AudioEngine::Pause(const ss_audio_request_handle_t handle)
{
    const auto request = impl_->Find(handle);
    return request ? request->Pause() : SS_STATUS_INVALID_HANDLE;
}

std::uint32_t AudioEngine::Resume(const ss_audio_request_handle_t handle)
{
    const auto request = impl_->Find(handle);
    return request ? request->Resume() : SS_STATUS_INVALID_HANDLE;
}

std::uint32_t AudioEngine::Stop(const ss_audio_request_handle_t handle,
                                const std::uint32_t terminal_reason)
{
    const auto request = impl_->Find(handle);
    return request ? request->Stop(terminal_reason) : SS_STATUS_INVALID_HANDLE;
}

std::uint32_t AudioEngine::Destroy(const ss_audio_request_handle_t handle)
{
    std::shared_ptr<AudioRequest> request;
    {
        std::lock_guard lock(impl_->mutex_);
        const auto found = impl_->requests_.find(handle);
        if (found == impl_->requests_.end()) {
            return SS_STATUS_INVALID_HANDLE;
        }
        if (found->second->OnDispatcherThread()) {
            return SS_STATUS_WRONG_STATE;
        }
        request = std::move(found->second);
        impl_->requests_.erase(found);
    }
    request->Destroy();
    return SS_STATUS_OK;
}

void AudioEngine::Shutdown()
{
    std::vector<std::shared_ptr<AudioRequest>> requests;
    std::shared_ptr<AudioSink> sink;
    {
        std::lock_guard lock(impl_->mutex_);
        if (impl_->closed_) {
            return;
        }
        impl_->closed_ = true;
        for (auto& [handle, request] : impl_->requests_) {
            static_cast<void>(handle);
            requests.push_back(std::move(request));
        }
        impl_->requests_.clear();
        sink = impl_->sink_;
    }
    for (const auto& request : requests) {
        request->Destroy();
    }
    if (sink) {
        sink->Shutdown();
    }
}

}  // namespace selectspeak::audio
