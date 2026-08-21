#include "../input_runtime.h"
#include "../../abi_guard.h"

#include <ole2.h>

#include <atomic>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

#include "../selection/selection_capture.h"

namespace selectspeak::input {
namespace {
constexpr int kHotkeyId = 1;
constexpr int kOcrHotkeyId = 2;
constexpr UINT kRebindMessage = WM_APP + 1;
constexpr UINT kCaptureMessage = WM_APP + 5;
constexpr UINT kRegisterOcrHotkeyMessage = WM_APP + 6;
constexpr UINT kUnregisterOcrHotkeyMessage = WM_APP + 7;
constexpr UINT kControlMessageTimeoutMs = 2000;
constexpr wchar_t kWindowClass[] = L"SelectSpeakNativeInputWindow";

struct RuntimeState {
    std::mutex lifecycle_mutex;
    std::thread message_thread;

    std::mutex ready_mutex;
    std::condition_variable ready_changed;
    bool ready = false;
    bool start_succeeded = false;

    std::atomic<bool> running{false};
    std::atomic<unsigned int> modifiers{0};
    std::atomic<unsigned int> virtual_key{0};
    std::atomic<unsigned int> capture_source{0};
    std::atomic<ULONGLONG> completed_capture_requested_at{0};
    std::atomic<HWND> window{nullptr};
    std::atomic<DWORD> message_thread_id{0};
    ss_capture_callback_t callback = nullptr;
    ss_activation_callback_t activation_callback = nullptr;
    void* callback_context = nullptr;

    OcrHotkeyHandler ocr_handler = nullptr;
    std::atomic<bool> ocr_dispatching{false};

    std::mutex error_mutex;
    std::string last_error;
    std::string last_capture_trace;
    std::wstring last_clipboard_fallback;
};

struct OcrHotkeyRegistration {
    unsigned int modifiers;
    unsigned int virtual_key;
    OcrHotkeyHandler handler;
    DWORD error = ERROR_SUCCESS;
};

RuntimeState g_runtime;

void SetError(const std::string& message)
{
    std::lock_guard lock(g_runtime.error_mutex);
    g_runtime.last_error = message;
}

void SetWindowsError(const char* action, DWORD code = GetLastError())
{
    SetError(std::string(action) + " failed with Windows error " +
             std::to_string(code));
}

void CompleteCapture(ULONGLONG requested_at, SelectionCapture capture)
{
    g_runtime.capture_source.store(
        static_cast<unsigned int>(capture.source));
    g_runtime.completed_capture_requested_at.store(requested_at);
    {
        std::lock_guard lock(g_runtime.error_mutex);
        g_runtime.last_capture_trace = std::move(capture.trace);
        g_runtime.last_clipboard_fallback =
            std::move(capture.clipboard_fallback_text);
    }
    SetError(capture.error);
    if (g_runtime.callback != nullptr) {
        g_runtime.callback(capture.text.c_str(), g_runtime.callback_context);
    }
}

void CaptureSelection(ULONGLONG requested_at, bool hotkey_activation)
{
    CompleteCapture(
        requested_at,
        CaptureSelectedText(hotkey_activation ? g_runtime.modifiers.load() : 0,
                            hotkey_activation ? g_runtime.virtual_key.load()
                                              : 0));
}

LRESULT CALLBACK WindowProcedure(HWND window, UINT message, WPARAM wparam,
                                 LPARAM lparam)
{
    try {
    switch (message) {
    case WM_HOTKEY:
        if (wparam == kHotkeyId && !g_runtime.ocr_dispatching.load()) {
            if (g_runtime.activation_callback != nullptr &&
                g_runtime.activation_callback(g_runtime.callback_context) != 0) {
                return 0;
            }
            CaptureSelection(GetTickCount64(), true);
            return 0;
        }
        if (wparam == kOcrHotkeyId && g_runtime.ocr_handler != nullptr &&
            !g_runtime.ocr_dispatching.exchange(true)) {
            g_runtime.ocr_handler();
            return 0;
        }
        break;
    case kCaptureMessage:
        if (!g_runtime.ocr_dispatching.load()) {
            CaptureSelection(static_cast<ULONGLONG>(wparam), false);
        }
        return 0;
    case kRegisterOcrHotkeyMessage: {
        auto* registration = reinterpret_cast<OcrHotkeyRegistration*>(lparam);
        if (registration == nullptr || registration->handler == nullptr ||
            registration->virtual_key == 0) {
            return 0;
        }
        if (!RegisterHotKey(window, kOcrHotkeyId,
                            registration->modifiers | MOD_NOREPEAT,
                            registration->virtual_key)) {
            registration->error = GetLastError();
            return 0;
        }
        g_runtime.ocr_handler = registration->handler;
        return 1;
    }
    case kUnregisterOcrHotkeyMessage:
        UnregisterHotKey(window, kOcrHotkeyId);
        g_runtime.ocr_handler = nullptr;
        return 1;
    case kRebindMessage: {
        const UINT previous_modifiers = g_runtime.modifiers.load();
        const UINT previous_key = g_runtime.virtual_key.load();
        UnregisterHotKey(window, kHotkeyId);
        if (RegisterHotKey(window, kHotkeyId,
                           static_cast<UINT>(wparam) | MOD_NOREPEAT,
                           static_cast<UINT>(lparam))) {
            g_runtime.modifiers.store(static_cast<UINT>(wparam));
            g_runtime.virtual_key.store(static_cast<UINT>(lparam));
            return 1;
        }
        const DWORD error = GetLastError();
        if (!RegisterHotKey(window, kHotkeyId,
                            previous_modifiers | MOD_NOREPEAT,
                            previous_key)) {
            SetError("RegisterHotKey failed with Windows error " +
                     std::to_string(error) +
                     "; restoring the previous hotkey also failed with Windows error " +
                     std::to_string(GetLastError()));
        } else {
            SetWindowsError("RegisterHotKey", error);
        }
        return 0;
    }
    case WM_CLOSE:
        UnregisterHotKey(window, kOcrHotkeyId);
        g_runtime.ocr_handler = nullptr;
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
    } catch (const std::exception& error) {
        SetError(error.what());
        return 0;
    } catch (...) {
        SetError("Unknown native input window-procedure error");
        return 0;
    }
}

void NotifyStartup(bool succeeded)
{
    {
        std::lock_guard lock(g_runtime.ready_mutex);
        g_runtime.start_succeeded = succeeded;
        g_runtime.ready = true;
    }
    g_runtime.ready_changed.notify_one();
}

void MessageLoop()
{
    g_runtime.message_thread_id.store(GetCurrentThreadId());
    const HRESULT apartment = OleInitialize(nullptr);
    if (FAILED(apartment)) {
        SetError("OleInitialize failed on the native input thread");
        NotifyStartup(false);
        g_runtime.message_thread_id.store(0);
        return;
    }

    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = WindowProcedure;
    window_class.hInstance = instance;
    window_class.lpszClassName = kWindowClass;
    const ATOM registered_class = RegisterClassW(&window_class);
    if (registered_class == 0 && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
        SetWindowsError("RegisterClassW");
        NotifyStartup(false);
        g_runtime.message_thread_id.store(0);
        OleUninitialize();
        return;
    }

    HWND window = CreateWindowExW(0, kWindowClass, L"", 0, 0, 0, 0, 0,
                                  HWND_MESSAGE, nullptr, instance, nullptr);
    bool succeeded = window != nullptr;
    if (succeeded) {
        g_runtime.window.store(window);
        succeeded = RegisterHotKey(
                        window, kHotkeyId,
                        g_runtime.modifiers.load() | MOD_NOREPEAT,
                        g_runtime.virtual_key.load()) != FALSE;
        if (!succeeded) {
            SetWindowsError("RegisterHotKey");
            DestroyWindow(window);
            g_runtime.window.store(nullptr);
        }
    } else {
        SetWindowsError("CreateWindowEx");
    }

    NotifyStartup(succeeded);
    if (!succeeded) {
        g_runtime.message_thread_id.store(0);
        OleUninitialize();
        return;
    }

    MSG message{};
    BOOL message_result = 0;
    while ((message_result = GetMessageW(&message, nullptr, 0, 0)) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    if (message_result == -1) {
        SetWindowsError("GetMessageW");
    }
    UnregisterHotKey(window, kOcrHotkeyId);
    UnregisterHotKey(window, kHotkeyId);
    g_runtime.window.store(nullptr);
    g_runtime.running.store(false);
    g_runtime.message_thread_id.store(0);
    ShutdownSelectionCaptureForThread();
    OleFlushClipboard();
    OleUninitialize();
}
}  // namespace

int Start(unsigned int modifiers, unsigned int virtual_key,
          ss_capture_callback_t callback,
          ss_activation_callback_t activation_callback, void* context)
{
    std::lock_guard lifecycle_lock(g_runtime.lifecycle_mutex);
    SetError({});
    if (g_runtime.running.load()) {
        SetError("The native input adapter is already running");
        return 1;
    }
    if (g_runtime.message_thread.joinable()) {
        g_runtime.message_thread.join();
    }
    if (callback == nullptr || virtual_key == 0) {
        SetError("A callback and virtual key are required");
        return 1;
    }

    g_runtime.callback = callback;
    g_runtime.activation_callback = activation_callback;
    g_runtime.callback_context = context;
    g_runtime.modifiers.store(modifiers);
    g_runtime.virtual_key.store(virtual_key);
    g_runtime.ready = false;
    g_runtime.start_succeeded = false;
    g_runtime.message_thread = std::thread(MessageLoop);
    {
        std::unique_lock ready_lock(g_runtime.ready_mutex);
        g_runtime.ready_changed.wait(ready_lock,
                                     [] { return g_runtime.ready; });
    }
    if (!g_runtime.start_succeeded) {
        g_runtime.message_thread.join();
        return 1;
    }
    g_runtime.running.store(true);
    return 0;
}

int Rebind(unsigned int modifiers, unsigned int virtual_key)
{
    SetError({});
    const HWND window = g_runtime.window.load();
    if (!g_runtime.running.load() || window == nullptr || virtual_key == 0) {
        SetError("The native input adapter is not running");
        return 1;
    }
    DWORD_PTR rebound = 0;
    if (!SendMessageTimeoutW(window, kRebindMessage, modifiers, virtual_key,
                             SMTO_ABORTIFHUNG | SMTO_BLOCK,
                             kControlMessageTimeoutMs, &rebound)) {
        SetWindowsError("SendMessageTimeoutW");
        return 1;
    }
    return rebound ? 0 : 1;
}

int CaptureNow()
{
    SetError({});
    const HWND window = g_runtime.window.load();
    if (!g_runtime.running.load() || window == nullptr) {
        SetError("The native input adapter is not running");
        return 1;
    }
    if (!PostMessageW(window, kCaptureMessage,
                      static_cast<WPARAM>(GetTickCount64()), 0)) {
        SetWindowsError("PostMessage");
        return 1;
    }
    return 0;
}

void Stop()
{
    std::lock_guard lifecycle_lock(g_runtime.lifecycle_mutex);
    g_runtime.running.store(false);
    const HWND window = g_runtime.window.load();
    if (window != nullptr) {
        if (!PostMessageW(window, WM_CLOSE, 0, 0)) {
            const DWORD thread_id = g_runtime.message_thread_id.load();
            if (thread_id != 0) {
                PostThreadMessageW(thread_id, WM_QUIT, 0, 0);
            }
        }
    }
    if (g_runtime.message_thread.joinable()) {
        if (GetCurrentThreadId() == g_runtime.message_thread_id.load()) {
            SetError(
                "The native input adapter cannot stop reentrantly from its callback thread");
            return;
        }
        g_runtime.message_thread.join();
    }
    g_runtime.callback = nullptr;
    g_runtime.activation_callback = nullptr;
    g_runtime.callback_context = nullptr;
}

unsigned int LastCaptureSource()
{
    return g_runtime.capture_source.load();
}

unsigned long long LastActivationTimeMs()
{
    return g_runtime.completed_capture_requested_at.load();
}

unsigned int LastCaptureTrace(char* buffer, unsigned int length)
{
    std::lock_guard lock(g_runtime.error_mutex);
    return selectspeak::abi::CopyString(g_runtime.last_capture_trace, buffer,
                                        length);
}

unsigned int LastClipboardFallback(wchar_t* buffer, unsigned int length)
{
    std::lock_guard lock(g_runtime.error_mutex);
    return selectspeak::abi::CopyString(g_runtime.last_clipboard_fallback,
                                        buffer, length);
}

unsigned int LastError(char* buffer, unsigned int length)
{
    std::lock_guard lock(g_runtime.error_mutex);
    return selectspeak::abi::CopyString(g_runtime.last_error, buffer, length);
}

void SetLastError(const std::string& message)
{
    SetError(message);
}

DWORD RegisterOcrHotkey(unsigned int modifiers, unsigned int virtual_key,
                        OcrHotkeyHandler handler)
{
    const HWND window = g_runtime.window.load();
    if (!g_runtime.running.load() || window == nullptr) {
        return ERROR_SERVICE_NOT_ACTIVE;
    }
    OcrHotkeyRegistration registration{modifiers, virtual_key, handler};
    const LRESULT registered = SendMessageW(
        window, kRegisterOcrHotkeyMessage, 0,
        reinterpret_cast<LPARAM>(&registration));
    if (!registered && registration.error == ERROR_SUCCESS) {
        return ERROR_GEN_FAILURE;
    }
    return registration.error;
}

void UnregisterOcrHotkey()
{
    const HWND window = g_runtime.window.load();
    if (g_runtime.running.load() && window != nullptr) {
        SendMessageW(window, kUnregisterOcrHotkeyMessage, 0, 0);
    }
}

void CompleteOcrDispatch()
{
    g_runtime.ocr_dispatching.store(false);
}

}  // namespace selectspeak::input
