#pragma once

#include <windows.h>

namespace selectspeak::input {

using OcrHotkeyHandler = void (*)();

DWORD RegisterOcrHotkey(unsigned int modifiers, unsigned int virtual_key,
                        OcrHotkeyHandler handler);
void UnregisterOcrHotkey();

}  // namespace selectspeak::input
