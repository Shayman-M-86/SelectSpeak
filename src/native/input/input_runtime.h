#pragma once

#include <windows.h>

#include "../api.h"

namespace selectspeak::input {

using OcrHotkeyHandler = void (*)();

int Start(unsigned int modifiers, unsigned int virtual_key,
          ss_capture_callback_t callback,
          ss_activation_callback_t activation_callback, void* context);
int Rebind(unsigned int modifiers, unsigned int virtual_key);
int CaptureNow();
void Stop();

unsigned int LastCaptureSource();
unsigned long long LastActivationTimeMs();
unsigned int LastError(char* buffer, unsigned int length);

DWORD RegisterOcrHotkey(unsigned int modifiers, unsigned int virtual_key,
                        OcrHotkeyHandler handler);
void UnregisterOcrHotkey();

}  // namespace selectspeak::input
