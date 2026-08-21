#include "../api.h"
#include "../abi_guard.h"
#include "input_runtime.h"

int ss_input_start(unsigned int modifiers, unsigned int virtual_key,
                   ss_capture_callback_t callback,
                   ss_activation_callback_t activation_callback,
                   void* context)
{
    return selectspeak::abi::GuardInt(
        selectspeak::input::SetLastError,
        [&] {
            return selectspeak::input::Start(
                modifiers, virtual_key, callback, activation_callback, context);
        });
}

int ss_input_rebind(unsigned int modifiers, unsigned int virtual_key)
{
    return selectspeak::abi::GuardInt(
        selectspeak::input::SetLastError,
        [&] { return selectspeak::input::Rebind(modifiers, virtual_key); });
}

int ss_input_capture_now()
{
    return selectspeak::abi::GuardInt(selectspeak::input::SetLastError,
                                      selectspeak::input::CaptureNow);
}

void ss_input_stop()
{
    selectspeak::abi::GuardVoid(selectspeak::input::SetLastError, [] {
        // OCR uses the input runtime's message window, so release it first.
        ss_ocr_stop();
        selectspeak::input::Stop();
    });
}

unsigned int ss_input_last_capture_source()
{
    return selectspeak::abi::GuardResult<unsigned int>(
        0, [](const std::string&) {},
        selectspeak::input::LastCaptureSource);
}

unsigned long long ss_input_last_activation_time_ms()
{
    return selectspeak::abi::GuardResult<unsigned long long>(
        0, [](const std::string&) {},
        selectspeak::input::LastActivationTimeMs);
}

unsigned int ss_input_last_capture_trace(char* buffer, unsigned int length)
{
    return selectspeak::abi::GuardResult<unsigned int>(
        0, [](const std::string&) {},
        [&] { return selectspeak::input::LastCaptureTrace(buffer, length); });
}

unsigned int ss_input_last_clipboard_fallback(wchar_t* buffer,
                                              unsigned int length)
{
    return selectspeak::abi::GuardResult<unsigned int>(
        0, [](const std::string&) {},
        [&] {
            return selectspeak::input::LastClipboardFallback(buffer, length);
        });
}

unsigned int ss_input_last_error(char* buffer, unsigned int length)
{
    return selectspeak::abi::GuardResult<unsigned int>(
        0, [](const std::string&) {},
        [&] { return selectspeak::input::LastError(buffer, length); });
}
