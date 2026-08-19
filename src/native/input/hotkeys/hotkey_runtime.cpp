#include "../input_runtime.h"

#include <roapi.h>

#include <atomic>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

#include "../selection/selection_capture.h"

namespace selectspeak::input {
namespace {
constexpr int kHotkeyId = 1;
constexpr int kOcrHotkeyId = 2;
constexpr UINT kRebindMessage = WM_APP + 1;
constexpr UINT kCaptureMessage = WM_APP + 5;
constexpr UINT kRegisterOcrHotkeyMessage = WM_APP + 6;
constexpr UINT kUnregisterOcrHotkeyMessage = WM_APP + 7;
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
    ss_capture_callback_t callback = nullptr;
    ss_activation_callback_t activation_callback = nullptr;
    void* callback_context = nullptr;

    OcrHotkeyHandler ocr_handler = nullptr;
    std::atomic<bool> ocr_dispatching{false};

    std::mutex error_mutex;
    std::string last_error;
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
    if (!capture.error.empty()) {
        SetError(capture.error);
    }
    if (g_runtime.callback != nullptr) {
        g_runtime.callback(capture.text.c_str(), g_runtime.callback_context);
    }
}

void CaptureSelection(ULONGLONG requested_at)
{
    CompleteCapture(requested_at,
                    CaptureSelectedText(g_runtime.modifiers.load()));
}

LRESULT CALLBACK WindowProcedure(HWND window, UINT message, WPARAM wparam,
                                 LPARAM lparam)
{
    switch (message) {
    case WM_HOTKEY:
        if (wparam == kHotkeyId && !g_runtime.ocr_dispatching.load()) {
            if (g_runtime.activation_callback != nullptr &&
                g_runtime.activation_callback(g_runtime.callback_context) != 0) {
                return 0;
            }
            CaptureSelection(GetTickCount64());
            return 0;
        }
        if (wparam == kOcrHotkeyId && g_runtime.ocr_handler != nullptr &&
            !g_runtime.ocr_dispatching.exchange(true)) {
            g_runtime.ocr_handler();
            g_runtime.ocr_dispatching.store(false);
            return 0;
        }
        break;
    case kCaptureMessage:
        if (!g_runtime.ocr_dispatching.load()) {
            CaptureSelection(static_cast<ULONGLONG>(wparam));
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
        RegisterHotKey(window, kHotkeyId, previous_modifiers | MOD_NOREPEAT,
                       previous_key);
        SetWindowsError("RegisterHotKey", error);
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
    const HRESULT apartment = RoInitialize(RO_INIT_MULTITHREADED);
    if (FAILED(apartment)) {
        SetError("RoInitialize failed on the native input thread");
        NotifyStartup(false);
        return;
    }

    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = WindowProcedure;
    window_class.hInstance = instance;
    window_class.lpszClassName = kWindowClass;
    RegisterClassW(&window_class);

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
        RoUninitialize();
        return;
    }

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    UnregisterHotKey(window, kOcrHotkeyId);
    UnregisterHotKey(window, kHotkeyId);
    g_runtime.window.store(nullptr);
    RoUninitialize();
}
}  // namespace

int Start(unsigned int modifiers, unsigned int virtual_key,
          ss_capture_callback_t callback,
          ss_activation_callback_t activation_callback, void* context)
{
    std::lock_guard lifecycle_lock(g_runtime.lifecycle_mutex);
    if (g_runtime.running.load()) {
        SetError("The native input adapter is already running");
        return 1;
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
    const HWND window = g_runtime.window.load();
    if (!g_runtime.running.load() || window == nullptr || virtual_key == 0) {
        SetError("The native input adapter is not running");
        return 1;
    }
    return SendMessageW(window, kRebindMessage, modifiers, virtual_key) ? 0 : 1;
}

int CaptureNow()
{
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
    if (!g_runtime.running.exchange(false)) {
        return;
    }
    const HWND window = g_runtime.window.load();
    if (window != nullptr) {
        PostMessageW(window, WM_CLOSE, 0, 0);
    }
    if (g_runtime.message_thread.joinable()) {
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

unsigned int LastError(char* buffer, unsigned int length)
{
    std::lock_guard lock(g_runtime.error_mutex);
    const unsigned int required =
        static_cast<unsigned int>(g_runtime.last_error.size() + 1);
    if (buffer != nullptr && length > 0) {
        const unsigned int count = required < length ? required : length;
        memcpy(buffer, g_runtime.last_error.c_str(), count - 1);
        buffer[count - 1] = '\0';
    }
    return required;
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

}  // namespace selectspeak::input
