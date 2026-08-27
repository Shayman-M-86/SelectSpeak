#include "speech_runtime_config.h"

#include <windows.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <mutex>
#include <system_error>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {
constexpr std::uintmax_t maximum_runtime_binary_size = 64ull * 1024 * 1024;
constexpr std::array<std::uint8_t, 7> runtime_config_marker = {
    '2', '7', '7', '4', '3', '1', '6'};

bool is_terminator_at(const std::vector<std::uint8_t>& bytes,
                      std::size_t offset, std::size_t width)
{
    if (offset + width > bytes.size()) {
        return false;
    }
    return std::all_of(bytes.begin() + offset,
                       bytes.begin() + offset + width,
                       [](std::uint8_t byte) { return byte == 0; });
}

std::optional<std::vector<std::uint8_t>> read_containing_string(
    const std::vector<std::uint8_t>& bytes,
    const std::vector<std::uint8_t>& marker, std::size_t character_width)
{
    const auto found = std::search(bytes.begin(), bytes.end(), marker.begin(),
                                   marker.end());
    if (found == bytes.end()) {
        return std::nullopt;
    }

    auto start = static_cast<std::size_t>(found - bytes.begin());
    while (start >= character_width &&
           !is_terminator_at(bytes, start - character_width, character_width)) {
        start -= character_width;
    }

    auto end = static_cast<std::size_t>(found - bytes.begin()) + marker.size();
    while (end + character_width <= bytes.size() &&
           !is_terminator_at(bytes, end, character_width)) {
        end += character_width;
    }
    if (end <= start || end - start > 16 * 1024) {
        return std::nullopt;
    }
    return std::vector<std::uint8_t>(bytes.begin() + start,
                                     bytes.begin() + end);
}

std::optional<std::string> utf16le_to_utf8(
    const std::vector<std::uint8_t>& bytes)
{
    if (bytes.empty() || bytes.size() % sizeof(wchar_t) != 0) {
        return std::nullopt;
    }
    std::wstring wide(bytes.size() / sizeof(wchar_t), L'\0');
    std::memcpy(wide.data(), bytes.data(), bytes.size());
    const auto required = WideCharToMultiByte(
        CP_UTF8, WC_ERR_INVALID_CHARS, wide.data(), static_cast<int>(wide.size()),
        nullptr, 0, nullptr, nullptr);
    if (required <= 0) {
        return std::nullopt;
    }
    std::string utf8(static_cast<std::size_t>(required), '\0');
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide.data(),
                             static_cast<int>(wide.size()), utf8.data(), required,
                             nullptr, nullptr)) {
        return std::nullopt;
    }
    return utf8;
}

std::optional<std::vector<std::uint8_t>> read_binary(
    const std::filesystem::path& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        return std::nullopt;
    }
    std::error_code error;
    const auto size = std::filesystem::file_size(path, error);
    if (error || size > maximum_runtime_binary_size) {
        return std::nullopt;
    }
    return std::vector<std::uint8_t>(std::istreambuf_iterator<char>(stream), {});
}

std::vector<std::filesystem::path> speech_extension_candidates()
{
    std::array<wchar_t, MAX_PATH + 1> windows_directory{};
    const auto length = GetWindowsDirectoryW(
        windows_directory.data(), static_cast<UINT>(windows_directory.size()));
    if (!length || length >= windows_directory.size()) {
        return {};
    }

    const auto system_apps = std::filesystem::path(windows_directory.data()) /
                             L"SystemApps";
    const std::array<std::wstring, 4> preferred_families = {
        L"MicrosoftWindows.Client.Core_cw5n1h2txyewy",
        L"MicrosoftWindows.Client.CoreAI_cw5n1h2txyewy",
        L"MicrosoftWindows.60719896.Speion_cw5n1h2txyewy",
        L"MicrosoftWindows.Client.CBS_cw5n1h2txyewy",
    };

    std::vector<std::filesystem::path> paths;
    std::unordered_set<std::wstring> seen;
    const auto add = [&](const std::filesystem::path& path) {
        const auto key = path.wstring();
        if (seen.insert(key).second) {
            paths.push_back(path);
        }
    };
    for (const auto& family : preferred_families) {
        add(system_apps / family / L"SpeechSynthesizerExtension.dll");
    }

    std::error_code error;
    for (std::filesystem::directory_iterator entries(system_apps, error), end;
         !error && entries != end; entries.increment(error)) {
        if (!entries->is_directory(error)) {
            error.clear();
            continue;
        }
        const auto name = entries->path().filename().wstring();
        if (name.rfind(L"MicrosoftWindows.", 0) != 0) {
            continue;
        }
        add(entries->path() / L"SpeechSynthesizerExtension.dll");
    }
    return paths;
}
}  // namespace

std::optional<std::string> read_speech_runtime_config(
    const std::vector<std::uint8_t>& bytes)
{
    const std::vector<std::uint8_t> utf8_marker(runtime_config_marker.begin(),
                                                runtime_config_marker.end());
    if (const auto runtime_data =
            read_containing_string(bytes, utf8_marker, 1)) {
        const std::string runtime_config(runtime_data->begin(),
                                         runtime_data->end());
        if (!runtime_config.empty()) {
            return runtime_config;
        }
    }

    std::vector<std::uint8_t> utf16_marker;
    utf16_marker.reserve(runtime_config_marker.size() * 2);
    for (const auto byte : runtime_config_marker) {
        utf16_marker.push_back(byte);
        utf16_marker.push_back(0);
    }
    if (const auto runtime_data =
            read_containing_string(bytes, utf16_marker, 2)) {
        return utf16le_to_utf8(*runtime_data);
    }
    return std::nullopt;
}

std::string legacy_speech_runtime_config()
{
    // Adapted from NaturalVoiceSAPIAdapter (MIT, copyright 2024 gexgd0419).
    // Extracted from Windows system components; not suitable for production or
    // redistribution. New voice packages reject it, which is why it is tried
    // only after the installed licence.
    return "Key:ZCjZ7nHDSLvf4gpELteM4AnzaWUjTpn7UkV7D@vvksl0w1SNgon6d1905WANbktDc9S39oaA4r29HJNayXvTq8fJsq";
}

std::vector<std::pair<std::string, std::string>>
speech_runtime_config_candidates()
{
    // The installed licence comes first: it is read from this machine, so it
    // matches whatever Windows currently ships and covers every package new
    // enough to use that format. The legacy key is the fallback for older
    // packages, which Windows leaves in place across updates without
    // re-encrypting them.
    std::vector<std::pair<std::string, std::string>> candidates;
    static std::once_flag discovery_once;
    static std::optional<std::string> installed_runtime;
    std::call_once(discovery_once, [] {
        installed_runtime = discover_speech_runtime_config();
    });
    if (installed_runtime) {
        candidates.emplace_back("installed Windows runtime",
                                *installed_runtime);
    }
    candidates.emplace_back("legacy compatibility",
                            legacy_speech_runtime_config());
    return candidates;
}

std::optional<std::string> discover_speech_runtime_config()
{
    for (const auto& path : speech_extension_candidates()) {
        const auto bytes = read_binary(path);
        if (!bytes) {
            continue;
        }
        if (auto runtime_config = read_speech_runtime_config(*bytes)) {
            return runtime_config;
        }
    }
    return std::nullopt;
}
