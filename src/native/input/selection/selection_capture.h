#pragma once

#include <string>

namespace selectspeak::input {

enum class CaptureSource : unsigned int {
    None = 0,
    UiAutomation = 1,
    WindowMessage = 2,
    SyntheticShortcut = 3,
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
