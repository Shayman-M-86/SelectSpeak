#pragma once

#include <windows.h>

#include <atomic>

#include "../../api.h"

namespace selectspeak::input {

class ShortcutRecorder {
public:
    DWORD Start(HWND window, UINT event_message, UINT stop_message,
                ss_record_callback_t callback, void* context);
    void Stop();
    bool active() const;
    void Deliver(unsigned int event, unsigned int modifiers,
                 unsigned int virtual_key) const;

private:
    static LRESULT CALLBACK Hook(int code, WPARAM message, LPARAM lparam);
    static unsigned int ModifierForKey(DWORD virtual_key);

    void PostEvent(unsigned int event, unsigned int modifiers,
                   unsigned int virtual_key) const;
    void Finish(unsigned int event);

    static ShortcutRecorder* active_recorder_;

    HWND window_ = nullptr;
    UINT event_message_ = 0;
    UINT stop_message_ = 0;
    HHOOK hook_ = nullptr;
    ss_record_callback_t callback_ = nullptr;
    void* context_ = nullptr;
    std::atomic<bool> recording_{false};
    std::atomic<bool> finishing_{false};
    std::atomic<unsigned int> modifiers_{0};
    std::atomic<unsigned int> chord_modifiers_{0};
    std::atomic<unsigned int> key_{0};
    std::atomic<bool> key_down_{false};
};

}  // namespace selectspeak::input
