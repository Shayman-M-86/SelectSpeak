#pragma once

#include <string>

namespace selectspeak::input {

enum class CaptureSource : unsigned int {
    None = 0,
    UiAutomation = 1,
    Clipboard = 2,
};

struct SelectionCapture {
    std::wstring text;
    CaptureSource source = CaptureSource::None;
    std::string error;
};

SelectionCapture CaptureSelectedText(unsigned int active_modifiers);

}  // namespace selectspeak::input
