#include "natural_voice.h"

#include "credential_provider.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
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
std::condition_variable started_condition;
std::shared_ptr<SpeechSynthesizer> synthesizer;
bool speaking = false;
bool synthesis_started = false;
bool stop_requested = false;
std::string last_error;

nv_audio_callback_t audio_callback = nullptr;
void* audio_context = nullptr;
nv_word_callback_t word_callback = nullptr;
void* word_context = nullptr;
nv_finished_callback_t finished_callback = nullptr;
void* finished_context = nullptr;

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
    try {
        function();
        return 0;
    } catch (const std::exception& error) {
        set_error(error.what());
        return 1;
    } catch (...) {
        set_error("Unknown native Natural Voice error");
        return 1;
    }
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
    return paths;
}
}  // namespace

std::uint32_t nv_list_voices(nv_voice_callback_t callback, void* context)
{
    std::uint32_t count = 0;
    const auto status = guarded([&] {
        ApartmentScope apartment;
        for (const auto& path : installed_voice_paths()) {
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
                             voice->Locale.c_str(), voice->LocalName.c_str(), context);
                }
            }
        }
    });
    return status == 0 ? count : 0;
}

int nv_initialize(const wchar_t* voice_path, const char* credential)
{
    return guarded([&] {
        if (!voice_path || !*voice_path) {
            throw std::invalid_argument("A Natural Voice package path is required");
        }

        nv_shutdown();
        auto config = EmbeddedSpeechConfig::FromPath(winrt::to_string(voice_path));
        config->SetSpeechSynthesisOutputFormat(
            SpeechSynthesisOutputFormat::Raw24Khz16BitMonoPcm);
        config->SetProperty(
            PropertyId::SpeechServiceResponse_RequestSentenceBoundary, "true");
        config->SetProperty(
            PropertyId::SpeechServiceResponse_RequestPunctuationBoundary, "false");

        auto probe = SpeechSynthesizer::FromConfig(config, nullptr);
        auto voices = probe->GetVoicesAsync().get();
        if (voices->Reason != ResultReason::VoicesListRetrieved ||
            voices->Voices.empty()) {
            throw std::runtime_error("No usable embedded voice in package: " +
                                     voices->ErrorDetails);
        }

        auto license = credential && *credential ? std::string(credential)
                                                  : legacy_narrator_credential();
        config->SetSpeechSynthesisVoice(voices->Voices.front()->Name, license);

        // Probe before publishing the engine. Newer Narrator packages can be
        // enumerated successfully but reject the legacy embedded-model license.
        // Failing here lets the Python "auto" backend select SAPI immediately.
        auto validation_synthesizer =
            SpeechSynthesizer::FromConfig(config, nullptr);
        auto validation = validation_synthesizer->SpeakText("");
        if (validation->Reason != ResultReason::SynthesizingAudioCompleted) {
            auto details =
                SpeechSynthesisCancellationDetails::FromResult(validation);
            throw std::runtime_error(
                "Natural Voice package rejected its embedded license: " +
                details->ErrorDetails);
        }

        auto stream = AudioOutputStream::CreatePushStream(
            [](std::uint8_t* data, std::uint32_t length) -> int {
                nv_audio_callback_t callback;
                void* context;
                {
                    std::lock_guard lock(state_mutex);
                    callback = audio_callback;
                    context = audio_context;
                }
                if (callback) {
                    callback(data, length, context);
                }
                return static_cast<int>(length);
            });
        auto created = SpeechSynthesizer::FromConfig(
            config, AudioConfig::FromStreamOutput(stream));

        created->SynthesisStarted += [](const SpeechSynthesisEventArgs&) {
            {
                std::lock_guard lock(state_mutex);
                synthesis_started = true;
            }
            started_condition.notify_all();
        };
        created->WordBoundary += [](
            const SpeechSynthesisWordBoundaryEventArgs& event) {
            if (event.BoundaryType == SpeechSynthesisBoundaryType::Punctuation) {
                return;
            }
            nv_word_callback_t callback;
            void* context;
            {
                std::lock_guard lock(state_mutex);
                callback = word_callback;
                context = word_context;
            }
            if (callback) {
                callback(event.AudioOffset, event.TextOffset, event.WordLength,
                         context);
            }
        };

        std::lock_guard lock(state_mutex);
        synthesizer = std::move(created);
        last_error.clear();
    });
}

void nv_set_audio_callback(nv_audio_callback_t callback, void* context)
{
    std::lock_guard lock(state_mutex);
    audio_callback = callback;
    audio_context = context;
}

void nv_set_word_callback(nv_word_callback_t callback, void* context)
{
    std::lock_guard lock(state_mutex);
    word_callback = callback;
    word_context = context;
}

void nv_set_finished_callback(nv_finished_callback_t callback, void* context)
{
    std::lock_guard lock(state_mutex);
    finished_callback = callback;
    finished_context = context;
}

int nv_speak(const wchar_t* text)
{
    if (!text) {
        set_error("Speech text must not be null");
        return 1;
    }

    std::shared_ptr<SpeechSynthesizer> active;
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
    }

    int status = guarded([&] {
        auto result = active->SpeakText(winrt::to_string(text));
        if (result->Reason != ResultReason::SynthesizingAudioCompleted) {
            {
                std::lock_guard lock(state_mutex);
                if (stop_requested) {
                    return;
                }
            }
            auto details = SpeechSynthesisCancellationDetails::FromResult(result);
            throw std::runtime_error(details->ErrorDetails);
        }
    });

    nv_finished_callback_t callback;
    void* context;
    {
        std::lock_guard lock(state_mutex);
        speaking = false;
        stop_requested = false;
        callback = finished_callback;
        context = finished_context;
    }
    if (callback) {
        callback(status, context);
    }
    return status;
}

int nv_stop()
{
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

void nv_shutdown()
{
    nv_stop();
    std::lock_guard lock(state_mutex);
    synthesizer.reset();
    speaking = false;
    synthesis_started = false;
    stop_requested = false;
}

std::uint32_t nv_last_error(char* buffer, std::uint32_t capacity)
{
    std::lock_guard lock(state_mutex);
    const auto required = static_cast<std::uint32_t>(last_error.size() + 1);
    if (buffer && capacity) {
        const auto count = std::min<std::uint32_t>(capacity - 1,
                                                   required - 1);
        std::memcpy(buffer, last_error.data(), count);
        buffer[count] = '\0';
    }
    return required;
}
