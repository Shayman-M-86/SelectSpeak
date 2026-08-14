#include "shortcut_recorder.h"

namespace selectspeak::input {

ShortcutRecorder* ShortcutRecorder::active_recorder_ = nullptr;

DWORD ShortcutRecorder::Start(HWND window, UINT event_message,
                              UINT stop_message,
                              ss_record_callback_t callback, void* context)
{
    if (recording_.load()) {
        return ERROR_BUSY;
    }
    if (window == nullptr || callback == nullptr) {
        return ERROR_INVALID_PARAMETER;
    }

    HMODULE module = nullptr;
    if (!GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&ShortcutRecorder::Hook), &module)) {
        return GetLastError();
    }

    window_ = window;
    event_message_ = event_message;
    stop_message_ = stop_message;
    callback_ = callback;
    context_ = context;
    modifiers_.store(0);
    chord_modifiers_.store(0);
    key_.store(0);
    key_down_.store(false);
    finishing_.store(false);
    active_recorder_ = this;
    hook_ = SetWindowsHookExW(WH_KEYBOARD_LL, Hook, module, 0);
    if (hook_ == nullptr) {
        const DWORD error = GetLastError();
        active_recorder_ = nullptr;
        callback_ = nullptr;
        context_ = nullptr;
        return error;
    }
    recording_.store(true);
    return ERROR_SUCCESS;
}

void ShortcutRecorder::Stop()
{
    recording_.store(false);
    if (hook_ != nullptr) {
        UnhookWindowsHookEx(hook_);
        hook_ = nullptr;
    }
    if (active_recorder_ == this) {
        active_recorder_ = nullptr;
    }
    callback_ = nullptr;
    context_ = nullptr;
}

bool ShortcutRecorder::active() const
{
    return recording_.load();
}

void ShortcutRecorder::Deliver(unsigned int event, unsigned int modifiers,
                               unsigned int virtual_key) const
{
    if (callback_ != nullptr) {
        callback_(event, modifiers, virtual_key, context_);
    }
}

unsigned int ShortcutRecorder::ModifierForKey(DWORD virtual_key)
{
    switch (virtual_key) {
    case VK_CONTROL:
    case VK_LCONTROL:
    case VK_RCONTROL:
        return MOD_CONTROL;
    case VK_MENU:
    case VK_LMENU:
    case VK_RMENU:
        return MOD_ALT;
    case VK_SHIFT:
    case VK_LSHIFT:
    case VK_RSHIFT:
        return MOD_SHIFT;
    case VK_LWIN:
    case VK_RWIN:
        return MOD_WIN;
    default:
        return 0;
    }
}

void ShortcutRecorder::PostEvent(unsigned int event, unsigned int modifiers,
                                 unsigned int virtual_key) const
{
    PostMessageW(window_, event_message_, event,
                 MAKELPARAM(modifiers, virtual_key));
}

void ShortcutRecorder::Finish(unsigned int event)
{
    if (finishing_.exchange(true)) {
        return;
    }
    PostEvent(event, chord_modifiers_.load(), key_.load());
    PostMessageW(window_, stop_message_, 0, 0);
}

LRESULT CALLBACK ShortcutRecorder::Hook(int code, WPARAM message,
                                        LPARAM lparam)
{
    ShortcutRecorder* recorder = active_recorder_;
    if (code != HC_ACTION || recorder == nullptr ||
        !recorder->recording_.load()) {
        return CallNextHookEx(nullptr, code, message, lparam);
    }

    const auto* key = reinterpret_cast<KBDLLHOOKSTRUCT*>(lparam);
    const bool pressed = message == WM_KEYDOWN || message == WM_SYSKEYDOWN;
    const bool released = message == WM_KEYUP || message == WM_SYSKEYUP;
    if (!pressed && !released) {
        return 1;
    }
    if (pressed && key->vkCode == VK_ESCAPE) {
        recorder->Finish(3);
        return 1;
    }

    const unsigned int modifier = ModifierForKey(key->vkCode);
    if (modifier != 0) {
        unsigned int modifiers = recorder->modifiers_.load();
        modifiers = pressed ? modifiers | modifier : modifiers & ~modifier;
        recorder->modifiers_.store(modifiers);
        if (pressed && !recorder->finishing_.load()) {
            recorder->PostEvent(1, modifiers, recorder->key_.load());
        }
        if (released && modifiers == 0 && !recorder->key_down_.load() &&
            recorder->key_.load() != 0) {
            recorder->Finish(2);
        }
        return 1;
    }

    if (pressed && recorder->key_.load() == 0) {
        recorder->key_.store(key->vkCode);
        recorder->chord_modifiers_.store(recorder->modifiers_.load());
        recorder->key_down_.store(true);
        recorder->PostEvent(1, recorder->modifiers_.load(), key->vkCode);
    } else if (released && key->vkCode == recorder->key_.load()) {
        recorder->key_down_.store(false);
        if (recorder->modifiers_.load() == 0) {
            recorder->Finish(2);
        }
    }
    return 1;
}

}  // namespace selectspeak::input
