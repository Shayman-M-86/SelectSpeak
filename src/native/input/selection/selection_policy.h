#pragma once

#include <cstdint>
#include <string_view>

namespace selectspeak::input {

enum class ClipboardRestoreDecision {
    Unavailable,
    Restore,
    SkipNewerContent,
};

enum class CopyOutcome {
    // No text came back, and no copy action was ever sent (e.g. WM_COPY was
    // skipped for a known-unsupported window class with no synthetic
    // fallback attempted yet).
    NotAttempted,
    // A copy action was sent and the clipboard changed in time; the caller
    // still decides whether the resulting text is actually usable.
    Completed,
    // A copy action was sent but the clipboard never changed before the
    // timeout. The target may still finish the copy later, so this must not
    // be treated the same as NotAttempted: callers must not fall back to
    // pre-capture clipboard content in this case.
    Unresolved,
};

bool IsKnownUnsupportedWindowCopyClass(std::string_view class_name);

ClipboardRestoreDecision DecideClipboardRestore(bool snapshot_available,
                                                 std::uint32_t captured_sequence,
                                                 std::uint32_t current_sequence);

CopyOutcome DecideCopyOutcome(bool action_sent, bool clipboard_changed);

}  // namespace selectspeak::input
