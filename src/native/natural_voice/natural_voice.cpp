#include "../api.h"
#include "../abi_guard.h"
#include "../audio/audio_engine.h"
#include "../audio/pcm_volume.h"

#include "speech_runtime_config.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <memory>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <roapi.h>
#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.ApplicationModel.h>
#include <winrt/Windows.Management.Deployment.h>
#include <speechapi_cxx.h>

using namespace Microsoft::CognitiveServices::Speech;
using namespace Microsoft::CognitiveServices::Speech::Audio;

namespace {
std::mutex state_mutex;
std::mutex lifecycle_mutex;
std::mutex speak_mutex;
std::condition_variable started_condition;
std::condition_variable speaking_condition;
std::condition_variable callback_condition;
std::shared_ptr<SpeechSynthesizer> synthesizer;
bool speaking = false;
bool synthesis_started = false;
bool stop_requested = false;
std::uint64_t generation = 0;
std::uint64_t speaking_generation = 0;
std::size_t callbacks_in_flight = 0;
std::string last_error;
std::uint32_t voice_volume_percent = 100;

struct DirectSynthesis {
    std::mutex mutex;
    std::vector<std::uint8_t> pcm;
    std::vector<ss_audio_boundary_t> boundaries;
    std::uint32_t text_base_offset_utf16 = 0;
    std::uint32_t volume_percent = 100;
    bool invalid_audio = false;
    bool invalid_boundary = false;
    bool cancelled = false;
};

DirectSynthesis* direct_synthesis = nullptr;

class DirectRegistration {
public:
    bool Activate(DirectSynthesis& operation)
    {
        std::lock_guard lock(state_mutex);
        if (direct_synthesis) {
            return false;
        }
        operation_ = &operation;
        direct_synthesis = operation_;
        return true;
    }

    ~DirectRegistration()
    {
        if (!operation_) {
            return;
        }
        std::unique_lock lock(state_mutex);
        callback_condition.wait(lock, [] { return callbacks_in_flight == 0; });
        if (direct_synthesis == operation_) {
            direct_synthesis = nullptr;
        }
    }

private:
    DirectSynthesis* operation_ = nullptr;
};

ss_audio_callback_t audio_callback = nullptr;
void* audio_context = nullptr;
ss_word_callback_t word_callback = nullptr;
void* word_context = nullptr;

class ApartmentScope {
public:
    ApartmentScope()
    {
        const auto result = RoInitialize(RO_INIT_MULTITHREADED);
        if (FAILED(result) && result != RPC_E_CHANGED_MODE) {
            winrt::check_hresult(result);
        }
        uninitialize_ = SUCCEEDED(result);
    }

    ~ApartmentScope()
    {
        if (uninitialize_) {
            RoUninitialize();
        }
    }

private:
    bool uninitialize_ = false;
};

void set_error(std::string message)
{
    std::lock_guard lock(state_mutex);
    last_error = std::move(message);
}

template <typename Function>
int guarded(Function&& function)
{
    return selectspeak::abi::GuardInt(set_error, [&] {
        set_error({});
        function();
        return 0;
    });
}

std::vector<std::string> installed_voice_paths()
{
    std::vector<std::string> paths;
    auto packages = winrt::Windows::Management::Deployment::PackageManager()
                        .FindPackagesForUser(L"");
    for (const auto& package : packages) {
        const auto name = package.Id().Name();
        const std::wstring_view name_view(name.c_str(), name.size());
        if (name_view.rfind(L"MicrosoftWindows.Voice.", 0) == 0) {
            paths.push_back(winrt::to_string(package.InstalledPath()));
        }
    }
    std::sort(paths.begin(), paths.end());
    return paths;
}

void reset_voice_engine(bool clear_callbacks)
{
    const int stop_status = ss_voice_stop();
    std::unique_lock lock(state_mutex);
    const bool quiesced = speaking_condition.wait_for(
        lock, std::chrono::seconds(2), [] { return !speaking; });
    ++generation;
    const bool callbacks_quiesced = callback_condition.wait_for(
        lock, std::chrono::seconds(2), [] { return callbacks_in_flight == 0; });
    synthesizer.reset();
    speaking = false;
    speaking_generation = 0;
    synthesis_started = false;
    stop_requested = false;
    if (clear_callbacks && callbacks_quiesced) {
        audio_callback = nullptr;
        audio_context = nullptr;
        word_callback = nullptr;
        word_context = nullptr;
    }
    if (stop_status != 0 || !quiesced || !callbacks_quiesced) {
        last_error = !callbacks_quiesced
                         ? "Timed out waiting for Natural Voice callbacks to finish"
                     : !quiesced
                         ? "Timed out waiting for Natural Voice synthesis to stop"
                         : "Natural Voice cancellation failed during shutdown";
    }
}
}  // namespace

std::uint32_t ss_voice_list(ss_voice_callback_t callback, void* context)
{
    std::uint32_t count = 0;
    const auto status = guarded([&] {
        ApartmentScope apartment;
        std::string package_errors;
        for (const auto& path : installed_voice_paths()) {
            try {
                auto config = EmbeddedSpeechConfig::FromPath(path);
                auto probe = SpeechSynthesizer::FromConfig(config, nullptr);
                auto result = probe->GetVoicesAsync().get();
                if (result->Reason != ResultReason::VoicesListRetrieved) {
                    continue;
                }
                const auto wide_path = winrt::to_hstring(path);
                for (const auto& voice : result->Voices) {
                    ++count;
                    if (callback) {
                        callback(wide_path.c_str(), voice->Name.c_str(),
                                 voice->Locale.c_str(), voice->LocalName.c_str(),
                                 context);
                    }
                }
            } catch (const std::exception& error) {
                if (!package_errors.empty()) {
                    package_errors += " | ";
                }
                package_errors += path + ": " + error.what();
            }
        }
        if (count == 0 && !package_errors.empty()) {
            throw std::runtime_error(package_errors);
        }
    });
    return status == 0 ? count : 0;
}

int ss_voice_initialize(const wchar_t* voice_path, const char* voice_name)
{
    return guarded([&] {
        std::lock_guard lifecycle_lock(lifecycle_mutex);
        if (!voice_path || !*voice_path || !voice_name || !*voice_name) {
            throw std::invalid_argument(
                "A Natural Voice package path and exact voice name are required");
        }

        reset_voice_engine(false);
        const auto path = winrt::to_string(voice_path);
        const auto create_config = [&] {
            auto config = EmbeddedSpeechConfig::FromPath(path);
            config->SetSpeechSynthesisOutputFormat(
                SpeechSynthesisOutputFormat::Raw24Khz16BitMonoPcm);
            config->SetProperty(
                PropertyId::SpeechServiceResponse_RequestSentenceBoundary,
                "true");
            config->SetProperty(
                PropertyId::SpeechServiceResponse_RequestPunctuationBoundary,
                "false");
            return config;
        };

        auto config = create_config();

        auto probe = SpeechSynthesizer::FromConfig(config, nullptr);
        auto voices = probe->GetVoicesAsync().get();
        if (voices->Reason != ResultReason::VoicesListRetrieved ||
            voices->Voices.empty()) {
            throw std::runtime_error("No usable embedded voice in package: " +
                                     voices->ErrorDetails);
        }
        const auto selected_voice = std::find_if(
            voices->Voices.begin(), voices->Voices.end(),
            [&](const auto& voice) { return voice->Name == voice_name; });
        if (selected_voice == voices->Voices.end()) {
            throw std::runtime_error("The requested voice is not available in package: " +
                                     std::string(voice_name));
        }

        // Voice packages come in two generations that take different
        // credentials, and nothing in a package says which it wants. The only
        // way to find out is to synthesise nothing with each in turn and keep
        // whichever is accepted; guessing from the package name would break
        // the moment Microsoft ships a voice that does not follow the pattern.
        const auto candidates = speech_runtime_config_candidates();
        std::string rejections;
        bool accepted = false;
        for (const auto& [source, candidate] : candidates) {
            auto candidate_config = create_config();
            candidate_config->SetSpeechSynthesisVoice(
                (*selected_voice)->Name, candidate);
            auto validation_synthesizer =
                SpeechSynthesizer::FromConfig(candidate_config, nullptr);
            auto validation = validation_synthesizer->SpeakText("");
            if (validation->Reason ==
                ResultReason::SynthesizingAudioCompleted) {
                config = std::move(candidate_config);
                accepted = true;
                break;
            }
            const auto details =
                SpeechSynthesisCancellationDetails::FromResult(validation);
            if (!rejections.empty()) {
                rejections += " | ";
            }
            rejections += source + ": " + details->ErrorDetails;
        }
        if (!accepted) {
            throw std::runtime_error(
                "The installed Natural Voice rejected every available speech "
                "runtime configuration: " +
                rejections);
        }

        std::uint64_t session_generation = 0;
        {
            std::lock_guard lock(state_mutex);
            session_generation = ++generation;
        }
        auto stream = AudioOutputStream::CreatePushStream(
            [session_generation](std::uint8_t* data,
                                 std::uint32_t length) -> int {
                ss_audio_callback_t callback;
                void* context;
                DirectSynthesis* direct;
                {
                    std::lock_guard lock(state_mutex);
                    if (generation != session_generation) {
                        return static_cast<int>(length);
                    }
                    callback = audio_callback;
                    context = audio_context;
                    direct = direct_synthesis;
                    if (callback || direct) {
                        ++callbacks_in_flight;
                    }
                }
                if (direct) {
                    std::lock_guard lock(direct->mutex);
                    try {
                        if ((length % 2) != 0 ||
                            direct->pcm.size() >
                                std::numeric_limits<std::size_t>::max() - length) {
                            direct->invalid_audio = true;
                        } else {
                            direct->pcm.insert(direct->pcm.end(), data,
                                               data + length);
                        }
                    } catch (...) {
                        direct->invalid_audio = true;
                    }
                } else if (callback) {
                    try {
                        callback(data, length, context);
                    } catch (...) {
                        set_error("The Natural Voice audio callback failed");
                    }
                }
                if (callback || direct) {
                    {
                        std::lock_guard lock(state_mutex);
                        --callbacks_in_flight;
                    }
                    callback_condition.notify_all();
                }
                return static_cast<int>(length);
            });
        auto created = SpeechSynthesizer::FromConfig(
            config, AudioConfig::FromStreamOutput(stream));

        created->SynthesisStarted += [session_generation](
                                         const SpeechSynthesisEventArgs&) {
            {
                std::lock_guard lock(state_mutex);
                if (generation != session_generation) {
                    return;
                }
                synthesis_started = true;
            }
            started_condition.notify_all();
        };
        created->WordBoundary += [session_generation](
            const SpeechSynthesisWordBoundaryEventArgs& event) {
            if (event.BoundaryType == SpeechSynthesisBoundaryType::Punctuation) {
                return;
            }
            ss_word_callback_t callback;
            void* context;
            DirectSynthesis* direct;
            {
                std::lock_guard lock(state_mutex);
                if (generation != session_generation) {
                    return;
                }
                callback = word_callback;
                context = word_context;
                direct = direct_synthesis;
                if (callback || direct) {
                    ++callbacks_in_flight;
                }
            }
            if (direct) {
                std::lock_guard lock(direct->mutex);
                const auto absolute_position =
                    static_cast<std::uint64_t>(direct->text_base_offset_utf16) +
                    event.TextOffset;
                const auto absolute_end = absolute_position + event.WordLength;
                if (absolute_position >
                        std::numeric_limits<std::uint32_t>::max() ||
                    absolute_end > std::numeric_limits<std::uint32_t>::max()) {
                    direct->invalid_boundary = true;
                } else {
                    try {
                        constexpr std::uint64_t ticks_per_second = 10'000'000;
                        constexpr std::uint64_t sample_rate = 24'000;
                        const auto seconds = event.AudioOffset / ticks_per_second;
                        const auto remainder = event.AudioOffset % ticks_per_second;
                        const auto frame_offset = seconds * sample_rate +
                            (remainder * sample_rate) / ticks_per_second;
                        direct->boundaries.push_back(
                            {frame_offset,
                             static_cast<std::uint32_t>(absolute_position),
                             event.WordLength});
                    } catch (...) {
                        direct->invalid_boundary = true;
                    }
                }
            } else if (callback) {
                try {
                    callback(event.AudioOffset, event.TextOffset,
                             event.WordLength, context);
                } catch (...) {
                    set_error("The Natural Voice word callback failed");
                }
            }
            if (callback || direct) {
                {
                    std::lock_guard lock(state_mutex);
                    --callbacks_in_flight;
                }
                callback_condition.notify_all();
            }
        };

        std::lock_guard lock(state_mutex);
        if (generation != session_generation) {
            throw std::runtime_error(
                "Natural Voice initialization was superseded");
        }
        synthesizer = std::move(created);
        last_error.clear();
    });
}

void ss_voice_set_audio_callback(ss_audio_callback_t callback, void* context)
{
    selectspeak::abi::GuardVoid(set_error, [&] {
        std::lock_guard lock(state_mutex);
        audio_callback = callback;
        audio_context = context;
    });
}

void ss_voice_set_word_callback(ss_word_callback_t callback, void* context)
{
    selectspeak::abi::GuardVoid(set_error, [&] {
        std::lock_guard lock(state_mutex);
        word_callback = callback;
        word_context = context;
    });
}

int VoiceSpeak(const wchar_t* text)
{
    if (!text) {
        set_error("Speech text must not be null");
        return 1;
    }

    std::shared_ptr<SpeechSynthesizer> active;
    std::uint64_t active_generation = 0;
    {
        std::lock_guard lock(state_mutex);
        if (!synthesizer) {
            last_error = "Natural Voice engine is not initialized";
            return 1;
        }
        if (speaking) {
            last_error = "Natural Voice engine is already speaking";
            return 1;
        }
        speaking = true;
        synthesis_started = false;
        stop_requested = false;
        active = synthesizer;
        active_generation = generation;
        speaking_generation = active_generation;
    }

    int status = guarded([&] {
        auto result = active->SpeakText(winrt::to_string(text));
        if (result->Reason != ResultReason::SynthesizingAudioCompleted) {
            {
                std::lock_guard lock(state_mutex);
                if (stop_requested) {
                    if (direct_synthesis) {
                        direct_synthesis->cancelled = true;
                    }
                    return;
                }
            }
            auto details = SpeechSynthesisCancellationDetails::FromResult(result);
            throw std::runtime_error(details->ErrorDetails);
        }
    });

    {
        std::lock_guard lock(state_mutex);
        if (generation == active_generation &&
            speaking_generation == active_generation) {
            speaking = false;
            speaking_generation = 0;
            stop_requested = false;
        }
    }
    speaking_condition.notify_all();
    return status;
}

int VoiceStop()
{
    set_error({});
    std::shared_ptr<SpeechSynthesizer> active;
    {
        std::unique_lock lock(state_mutex);
        if (!synthesizer || !speaking) {
            return 0;
        }
        // The embedded SDK ignores cancellation before SynthesisStarted.
        if (!started_condition.wait_for(lock, std::chrono::seconds(2),
                                        [] { return synthesis_started || !speaking; })) {
            last_error = "Timed out waiting for synthesis to start before stopping";
            return 1;
        }
        if (!speaking) {
            return 0;
        }
        stop_requested = true;
        active = synthesizer;
    }
    return guarded([&] { active->StopSpeakingAsync().wait(); });
}

int ss_voice_speak(const wchar_t* text)
{
    std::lock_guard speak_lock(speak_mutex);
    return selectspeak::abi::GuardInt(set_error,
                                      [&] { return VoiceSpeak(text); });
}

std::uint32_t ss_voice_set_volume(const std::uint32_t volume_percent)
{
    if (volume_percent > 100) {
        return SS_STATUS_INVALID_ARGUMENT;
    }
    std::lock_guard lock(state_mutex);
    voice_volume_percent = volume_percent;
    return SS_STATUS_OK;
}

std::uint32_t VoiceSynthesizeToAudio(
    const ss_audio_request_handle_t audio_request,
    const std::uint64_t request_id, const wchar_t* const text,
    const std::uint32_t text_base_offset_utf16,
    ss_natural_synthesis_result_t* const result)
{
    if (!result || result->size != sizeof(ss_natural_synthesis_result_t) ||
        audio_request == SS_INVALID_AUDIO_REQUEST_HANDLE || request_id == 0 ||
        !text) {
        return SS_STATUS_INVALID_ARGUMENT;
    }
    result->status = SS_STATUS_OK;
    result->generated_frames = 0;
    result->synthesis_duration_us = 0;
    result->buffered_frames_after_submit = 0;

    std::lock_guard speak_lock(speak_mutex);
    DirectSynthesis operation;
    operation.text_base_offset_utf16 = text_base_offset_utf16;
    DirectRegistration registration;
    {
        std::lock_guard lock(state_mutex);
        operation.volume_percent = voice_volume_percent;
    }
    if (!registration.Activate(operation)) {
        result->status = SS_STATUS_WRONG_STATE;
        return result->status;
    }

    const auto started_at = std::chrono::steady_clock::now();
    const auto speak_status = VoiceSpeak(text);
    const auto finished_at = std::chrono::steady_clock::now();
    result->synthesis_duration_us =
        static_cast<std::uint64_t>(std::chrono::duration_cast<
            std::chrono::microseconds>(finished_at - started_at).count());
    if (operation.cancelled) {
        result->status = SS_STATUS_CLOSED;
        return result->status;
    }
    if (speak_status != 0) {
        result->status = SS_STATUS_INTERNAL_ERROR;
        return result->status;
    }

    std::lock_guard operation_lock(operation.mutex);
    if (operation.invalid_audio || (operation.pcm.size() % 2) != 0) {
        set_error("Natural Voice produced invalid 16-bit mono PCM");
        result->status = SS_STATUS_INTERNAL_ERROR;
        return result->status;
    }
    const auto generated_frames = operation.pcm.size() / 2;
    if (operation.invalid_boundary ||
        std::any_of(operation.boundaries.begin(), operation.boundaries.end(),
                    [generated_frames](const ss_audio_boundary_t& boundary) {
                        return boundary.frame_offset > generated_frames;
                    })) {
        set_error("Natural Voice produced an invalid word boundary");
        result->status = SS_STATUS_INVALID_BOUNDARY;
        return result->status;
    }

    if (operation.volume_percent != 100) {
        selectspeak::audio::ScalePcm16(operation.pcm,
                                       operation.volume_percent);
    }

    constexpr std::uint64_t frames_per_slice = 24'000 * 3;
    std::size_t boundary_index = 0;
    std::uint64_t slice_start = 0;
    std::uint32_t submit_status = SS_STATUS_OK;
    while (slice_start < generated_frames) {
        const auto slice_frames =
            std::min(frames_per_slice, generated_frames - slice_start);
        const auto slice_end = slice_start + slice_frames;
        std::vector<ss_audio_boundary_t> slice_boundaries;
        while (boundary_index < operation.boundaries.size() &&
               operation.boundaries[boundary_index].frame_offset <=
                   slice_end) {
            auto boundary = operation.boundaries[boundary_index++];
            boundary.frame_offset -= slice_start;
            slice_boundaries.push_back(boundary);
        }

        ss_audio_submit_result_t submit_result{
            sizeof(ss_audio_submit_result_t), 0, 0, 0};
        submit_status =
            selectspeak::audio::ProductionAudioEngine().SubmitForRequest(
                audio_request, request_id,
                operation.pcm.data() + slice_start * sizeof(std::int16_t),
                slice_frames * sizeof(std::int16_t),
                slice_boundaries.empty() ? nullptr : slice_boundaries.data(),
                static_cast<std::uint32_t>(slice_boundaries.size()),
                &submit_result);
        if (submit_status != SS_STATUS_OK) {
            break;
        }
        result->buffered_frames_after_submit =
            submit_result.buffered_frames_after_submit;
        slice_start = slice_end;
    }
    result->status = submit_status;
    if (submit_status == SS_STATUS_OK) {
        result->generated_frames = generated_frames;
    }
    return submit_status;
}

std::uint32_t ss_voice_synthesize_to_audio(
    const ss_audio_request_handle_t audio_request,
    const std::uint64_t request_id, const wchar_t* const text,
    const std::uint32_t text_base_offset_utf16,
    ss_natural_synthesis_result_t* const result)
{
    return selectspeak::abi::GuardResult<std::uint32_t>(
        SS_STATUS_INTERNAL_ERROR, set_error, [&] {
            return VoiceSynthesizeToAudio(audio_request, request_id, text,
                                          text_base_offset_utf16, result);
        });
}

int ss_voice_stop()
{
    return selectspeak::abi::GuardInt(set_error, VoiceStop);
}

void ss_voice_shutdown()
{
    selectspeak::abi::GuardVoid(set_error, [] {
        std::lock_guard lifecycle_lock(lifecycle_mutex);
        reset_voice_engine(true);
    });
}

std::uint32_t ss_voice_last_error(char* buffer, std::uint32_t capacity)
{
    return selectspeak::abi::GuardResult<std::uint32_t>(
        0, [](const std::string&) {}, [&] {
            std::lock_guard lock(state_mutex);
            return selectspeak::abi::CopyString(last_error, buffer, capacity);
        });
}
