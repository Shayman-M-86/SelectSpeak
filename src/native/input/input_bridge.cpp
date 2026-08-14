#include "../api.h"
#include "input_runtime.h"

int ss_input_start(unsigned int modifiers, unsigned int virtual_key,
                   ss_capture_callback_t callback,
                   ss_activation_callback_t activation_callback,
                   void* context)
{
    return selectspeak::input::Start(modifiers, virtual_key, callback,
                                     activation_callback, context);
}

int ss_input_rebind(unsigned int modifiers, unsigned int virtual_key)
{
    return selectspeak::input::Rebind(modifiers, virtual_key);
}

int ss_input_capture_now()
{
    return selectspeak::input::CaptureNow();
}

int ss_input_record_start(ss_record_callback_t callback, void* context)
{
    return selectspeak::input::StartRecording(callback, context);
}

void ss_input_record_stop()
{
    selectspeak::input::StopRecording();
}

void ss_input_stop()
{
    // OCR uses the input runtime's message window, so release it first.
    ss_ocr_stop();
    selectspeak::input::Stop();
}

unsigned int ss_input_last_capture_source()
{
    return selectspeak::input::LastCaptureSource();
}

unsigned long long ss_input_last_activation_time_ms()
{
    return selectspeak::input::LastActivationTimeMs();
}

unsigned int ss_input_last_error(char* buffer, unsigned int length)
{
    return selectspeak::input::LastError(buffer, length);
}
