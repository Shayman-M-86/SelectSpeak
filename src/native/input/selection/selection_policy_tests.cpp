#include "selection_policy.h"

#include <cstdlib>
#include <iostream>

using selectspeak::input::ClipboardRestoreDecision;
using selectspeak::input::CopyOutcome;
using selectspeak::input::DecideClipboardRestore;
using selectspeak::input::DecideCopyOutcome;
using selectspeak::input::IsKnownUnsupportedWindowCopyClass;

namespace {

void Expect(bool condition, const char* message)
{
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main()
{
    Expect(IsKnownUnsupportedWindowCopyClass("Chrome_WidgetWin_1"),
           "Chromium widget windows should skip WM_COPY");
    Expect(IsKnownUnsupportedWindowCopyClass("Chrome_RenderWidgetHostHWND"),
           "Chromium renderer windows should skip WM_COPY");
    Expect(!IsKnownUnsupportedWindowCopyClass("Edit"),
           "Native edit controls should probe WM_COPY");
    Expect(!IsKnownUnsupportedWindowCopyClass("CustomEditor"),
           "Unknown controls should probe their WM_COPY result");

    Expect(DecideClipboardRestore(false, 10, 10) ==
               ClipboardRestoreDecision::Unavailable,
           "A missing snapshot cannot be restored");
    Expect(DecideClipboardRestore(true, 10, 10) ==
               ClipboardRestoreDecision::Restore,
           "An unchanged clipboard sequence should be restored");
    Expect(DecideClipboardRestore(true, 10, 11) ==
               ClipboardRestoreDecision::SkipNewerContent,
           "Newer clipboard content must not be overwritten");

    Expect(DecideCopyOutcome(false, false) == CopyOutcome::NotAttempted,
           "No copy action sent means nothing was attempted");
    Expect(DecideCopyOutcome(true, true) == CopyOutcome::Completed,
           "A sent copy whose clipboard changed in time is completed");
    // Regression: an Electron/Chromium target (e.g. VS Code) can take longer
    // than a short timeout to respond to a synthetic Ctrl+C. A copy that was
    // sent but arrives after the wait ends must be reported as unresolved,
    // never silently treated as if nothing was selected - the caller uses
    // this to avoid speaking stale pre-capture clipboard content.
    Expect(DecideCopyOutcome(true, false) == CopyOutcome::Unresolved,
           "A sent copy that times out before the clipboard changes is "
           "unresolved, not empty");
    return 0;
}
