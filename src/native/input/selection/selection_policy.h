#pragma once

#include <cstdint>
#include <string_view>

namespace selectspeak::input {

enum class ClipboardRestoreDecision {
    Unavailable,
    Restore,
    SkipNewerContent,
};

bool IsKnownUnsupportedWindowCopyClass(std::string_view class_name);

ClipboardRestoreDecision DecideClipboardRestore(bool snapshot_available,
                                                 std::uint32_t captured_sequence,
                                                 std::uint32_t current_sequence);

}  // namespace selectspeak::input
