#pragma once

#include <string>

namespace selectspeak::input {

enum class CaptureSource : unsigned int {
    None = 0,
    UiAutomation = 1,
    WindowMessage = 2,
    SyntheticShortcut = 3,
    // A copy action was sent (WM_COPY or synthetic Ctrl+C) but the clipboard
    // never changed before the timeout. Unlike None, this is not "nothing was
    // selected" — the target may still complete the copy after we stopped
    // waiting, so its content must never be treated as this capture's result
    // or as a stand-in for the pre-capture clipboard fallback.
    Unresolved = 4,
};

struct SelectionCapture {
    std::wstring text;
    // What the clipboard held before this capture touched it. Copied by value
    // up front so a fallback read never depends on restoration succeeding.
    std::wstring clipboard_fallback_text;
    CaptureSource source = CaptureSource::None;
    std::string error;
    std::string trace;
};

SelectionCapture CaptureSelectedText(unsigned int active_modifiers,
                                     unsigned int active_virtual_key);
void ShutdownSelectionCaptureForThread();

}  // namespace selectspeak::input
