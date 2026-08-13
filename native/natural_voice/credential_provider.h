#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

// Finds the credential embedded in the Windows speech runtime currently
// installed on this machine. The value is returned in memory only and must
// never be logged or persisted.
std::optional<std::string> installed_narrator_credential();

// Kept separate from filesystem discovery so the binary parser can be tested
// without reading or copying Windows components.
std::optional<std::string> extract_installed_narrator_credential(
    const std::vector<std::uint8_t>& bytes);
