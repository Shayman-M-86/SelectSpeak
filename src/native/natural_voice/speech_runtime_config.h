#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

// Discovers the runtime configuration required by Microsoft's locally
// installed speech components. The value remains in memory and must never be
// logged, persisted, uploaded, or otherwise transmitted.
std::optional<std::string> discover_speech_runtime_config();

// Kept separate from filesystem discovery so parsing can be tested without
// reading or copying Windows components.
std::optional<std::string> read_speech_runtime_config(
    const std::vector<std::uint8_t>& bytes);
