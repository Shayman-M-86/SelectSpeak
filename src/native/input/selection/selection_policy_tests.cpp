#include "selection_policy.h"

#include <cstdlib>
#include <iostream>

using selectspeak::input::ClipboardRestoreDecision;
using selectspeak::input::DecideClipboardRestore;
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
    return 0;
}
