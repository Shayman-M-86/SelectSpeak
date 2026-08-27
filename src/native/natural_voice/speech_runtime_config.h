#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

// Discovers the runtime configuration required by Microsoft's locally
// installed speech components. The value remains in memory and must never be
// logged, persisted, uploaded, or otherwise transmitted.
std::optional<std::string> discover_speech_runtime_config();

// The credential accepted by voice packages that predate the licence format
// discover_speech_runtime_config() reads. Kept isolated because Microsoft does
// not expose Narrator voices as a supported third-party API and has changed
// their protection at least once: packages built before that change reject the
// installed licence outright, and packages built after it reject this.
std::string legacy_speech_runtime_config();

// Every credential worth trying against a voice package, in the order to try
// them. A package accepts exactly one of these and there is no way to tell
// which from the package itself, so callers are expected to attempt each in
// turn rather than choose.
std::vector<std::pair<std::string, std::string>> speech_runtime_config_candidates();

// Kept separate from filesystem discovery so parsing can be tested without
// reading or copying Windows components.
std::optional<std::string> read_speech_runtime_config(
    const std::vector<std::uint8_t>& bytes);
