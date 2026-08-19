#include "speech_runtime_config.h"

#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

namespace {
bool expect_equal(const std::optional<std::string>& actual,
                  const std::string& expected, const char* test)
{
    if (actual && *actual == expected) {
        return true;
    }
    std::cerr << test << " failed\n";
    return false;
}
}  // namespace

int main()
{
    bool passed = true;
    const std::string utf8_runtime_config = "Runtime:alpha-2774316-omega";
    std::vector<std::uint8_t> utf8 = {9, 0};
    utf8.insert(utf8.end(), utf8_runtime_config.begin(),
                utf8_runtime_config.end());
    utf8.insert(utf8.end(), {0, 7});
    passed &= expect_equal(read_speech_runtime_config(utf8),
                           utf8_runtime_config, "UTF-8 runtime configuration");

    const std::string utf16_runtime_config = "Wide-2774316-runtime";
    std::vector<std::uint8_t> utf16 = {8, 0, 0, 0};
    for (const auto character : utf16_runtime_config) {
        utf16.push_back(static_cast<std::uint8_t>(character));
        utf16.push_back(0);
    }
    utf16.insert(utf16.end(), {0, 0, 3});
    passed &= expect_equal(read_speech_runtime_config(utf16),
                           utf16_runtime_config,
                           "UTF-16 runtime configuration");

    passed &= !read_speech_runtime_config({1, 2, 3}).has_value();

    // Older voice packages take the legacy key rather than the installed
    // licence, so it has to remain in the list and has to come last: trying it
    // first would hand newer packages a credential they reject.
    const auto candidates = speech_runtime_config_candidates();
    if (candidates.empty() ||
        candidates.back().second != legacy_speech_runtime_config()) {
        std::cerr << "legacy runtime configuration fallback failed\n";
        passed = false;
    }

    if (!passed) {
        return 1;
    }
    std::cout << "speech runtime configuration tests passed\n";
    return 0;
}
