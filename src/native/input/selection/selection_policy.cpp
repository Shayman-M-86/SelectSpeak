#include "selection_policy.h"

namespace selectspeak::input {

bool IsKnownUnsupportedWindowCopyClass(std::string_view class_name)
{
    return class_name.rfind("Chrome_WidgetWin_", 0) == 0 ||
           class_name == "Chrome_RenderWidgetHostHWND";
}

ClipboardRestoreDecision DecideClipboardRestore(
    bool snapshot_available, std::uint32_t captured_sequence,
    std::uint32_t current_sequence)
{
    if (!snapshot_available) {
        return ClipboardRestoreDecision::Unavailable;
    }
    return captured_sequence == current_sequence
               ? ClipboardRestoreDecision::Restore
               : ClipboardRestoreDecision::SkipNewerContent;
}

CopyOutcome DecideCopyOutcome(bool action_sent, bool clipboard_changed)
{
    if (!action_sent) {
        return CopyOutcome::NotAttempted;
    }
    return clipboard_changed ? CopyOutcome::Completed : CopyOutcome::Unresolved;
}

}  // namespace selectspeak::input
