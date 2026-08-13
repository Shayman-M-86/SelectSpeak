#include <windows.h>
#include <ole2.h>
#include <roapi.h>
#include <uiautomation.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "../api.h"
#include "input_runtime.h"

namespace {
constexpr int kHotkeyId = 1;
constexpr int kOcrHotkeyId = 2;
constexpr UINT kRebindMessage = WM_APP + 1;
constexpr UINT kStartRecordingMessage = WM_APP + 2;
constexpr UINT kStopRecordingMessage = WM_APP + 3;
constexpr UINT kRecordingEventMessage = WM_APP + 4;
constexpr UINT kCaptureMessage = WM_APP + 5;
constexpr UINT kRegisterOcrHotkeyMessage = WM_APP + 6;
constexpr UINT kUnregisterOcrHotkeyMessage = WM_APP + 7;
constexpr DWORD kClipboardTimeoutMs = 1000;
constexpr wchar_t kWindowClass[] = L"SelectSpeakNativeInputWindow";

struct State {
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
    HWND window = nullptr;
    ss_capture_callback_t callback = nullptr;
    ss_activation_callback_t activation_callback = nullptr;
    void* callback_context = nullptr;
    HHOOK recording_hook = nullptr;
    ss_record_callback_t recording_callback = nullptr;
    void* recording_context = nullptr;
    std::atomic<bool> recording{false};
    std::atomic<bool> recording_finishing{false};
    std::atomic<unsigned int> recorded_modifiers{0};
    std::atomic<unsigned int> recorded_chord_modifiers{0};
    std::atomic<unsigned int> recorded_key{0};
    std::atomic<bool> recorded_key_down{false};
    selectspeak::input::OcrHotkeyHandler ocr_handler = nullptr;
    std::atomic<bool> ocr_dispatching{false};

    std::mutex error_mutex;
    std::string last_error;
};

State g_state;

struct OcrHotkeyRegistration {
    unsigned int modifiers;
    unsigned int virtual_key;
    selectspeak::input::OcrHotkeyHandler handler;
    DWORD error = ERROR_SUCCESS;
};

bool OpenClipboardWithRetry();

bool IsUnsupportedClipboardFormat(UINT format) {
    return format == CF_OWNERDISPLAY || format == CF_DSPTEXT ||
           format == CF_DSPBITMAP || format == CF_DSPMETAFILEPICT ||
           format == CF_DSPENHMETAFILE ||
           (format >= CF_PRIVATEFIRST && format <= CF_PRIVATELAST) ||
           (format >= CF_GDIOBJFIRST && format <= CF_GDIOBJLAST);
}

HANDLE DuplicateClipboardData(UINT format, HANDLE source) {
    if (format == CF_ENHMETAFILE) {
        return CopyEnhMetaFileW(static_cast<HENHMETAFILE>(source), nullptr);
    }
    return OleDuplicateData(source, format, GMEM_MOVEABLE);
}

void ReleaseClipboardData(UINT format, HANDLE data) {
    if (data == nullptr) {
        return;
    }
    if (format == CF_BITMAP || format == CF_PALETTE) {
        DeleteObject(data);
    } else if (format == CF_METAFILEPICT) {
        auto* picture = static_cast<METAFILEPICT*>(GlobalLock(data));
        if (picture != nullptr) {
            DeleteMetaFile(picture->hMF);
            GlobalUnlock(data);
        }
        GlobalFree(data);
    } else if (format == CF_ENHMETAFILE) {
        DeleteEnhMetaFile(static_cast<HENHMETAFILE>(data));
    } else {
        GlobalFree(data);
    }
}

struct ClipboardEntry {
    UINT format = 0;
    HANDLE data = nullptr;

    ClipboardEntry(UINT entry_format, HANDLE entry_data)
        : format(entry_format), data(entry_data) {}
    ClipboardEntry(const ClipboardEntry&) = delete;
    ClipboardEntry& operator=(const ClipboardEntry&) = delete;
    ClipboardEntry(ClipboardEntry&& other) noexcept
        : format(other.format), data(other.data) {
        other.data = nullptr;
    }
    ClipboardEntry& operator=(ClipboardEntry&&) = delete;
    ~ClipboardEntry() { ReleaseClipboardData(format, data); }
};

class ClipboardSnapshot {
public:
    bool Capture() {
        if (!OpenClipboardWithRetry()) {
            return false;
        }
        bool captured_all = true;
        UINT format = 0;
        while ((format = EnumClipboardFormats(format)) != 0) {
            if (IsUnsupportedClipboardFormat(format)) {
                continue;
            }
            HANDLE source = GetClipboardData(format);
            HANDLE duplicate =
                source == nullptr ? nullptr : DuplicateClipboardData(format, source);
            if (duplicate != nullptr) {
                entries_.emplace_back(format, duplicate);
            } else {
                captured_all = false;
            }
        }
        CloseClipboard();
        return captured_all;
    }

    bool Restore() {
        if (!OpenClipboardWithRetry()) {
            return false;
        }
        if (!EmptyClipboard()) {
            CloseClipboard();
            return false;
        }
        bool restored_all = true;
        for (auto& entry : entries_) {
            if (SetClipboardData(entry.format, entry.data) == nullptr) {
                restored_all = false;
            } else {
                entry.data = nullptr;  // Clipboard ownership transferred.
            }
        }
        CloseClipboard();
        return restored_all;
    }

private:
    std::vector<ClipboardEntry> entries_;
};

void SetError(const std::string& message) {
    std::lock_guard lock(g_state.error_mutex);
    g_state.last_error = message;
}

void SetWindowsError(const char* action) {
    const DWORD code = GetLastError();
    SetError(std::string(action) + " failed with Windows error " +
             std::to_string(code));
}

unsigned int ModifierForKey(DWORD virtual_key) {
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

void PostRecordingEvent(unsigned int event, unsigned int modifiers,
                        unsigned int virtual_key) {
    PostMessageW(g_state.window, kRecordingEventMessage, event,
                 MAKELPARAM(modifiers, virtual_key));
}

void FinishRecording(unsigned int event) {
    if (g_state.recording_finishing.exchange(true)) {
        return;
    }
    PostRecordingEvent(event, g_state.recorded_chord_modifiers.load(),
                       g_state.recorded_key.load());
    PostMessageW(g_state.window, kStopRecordingMessage, 0, 0);
}

LRESULT CALLBACK RecordingHook(int code, WPARAM message, LPARAM lparam) {
    if (code != HC_ACTION || !g_state.recording.load()) {
        return CallNextHookEx(nullptr, code, message, lparam);
    }
    const auto* key = reinterpret_cast<KBDLLHOOKSTRUCT*>(lparam);
    const bool pressed = message == WM_KEYDOWN || message == WM_SYSKEYDOWN;
    const bool released = message == WM_KEYUP || message == WM_SYSKEYUP;
    if (!pressed && !released) {
        return 1;
    }

    if (pressed && key->vkCode == VK_ESCAPE) {
        FinishRecording(3);
        return 1;
    }

    const unsigned int modifier = ModifierForKey(key->vkCode);
    if (modifier != 0) {
        unsigned int modifiers = g_state.recorded_modifiers.load();
        if (pressed) {
            modifiers |= modifier;
        } else {
            modifiers &= ~modifier;
        }
        g_state.recorded_modifiers.store(modifiers);
        if (pressed && !g_state.recording_finishing.load()) {
            PostRecordingEvent(1, modifiers, g_state.recorded_key.load());
        }
        if (released && modifiers == 0 &&
            !g_state.recorded_key_down.load() &&
            g_state.recorded_key.load() != 0) {
            FinishRecording(2);
        }
        return 1;
    }

    if (pressed && g_state.recorded_key.load() == 0) {
        g_state.recorded_key.store(key->vkCode);
        g_state.recorded_chord_modifiers.store(
            g_state.recorded_modifiers.load());
        g_state.recorded_key_down.store(true);
        PostRecordingEvent(1, g_state.recorded_modifiers.load(), key->vkCode);
    } else if (released && key->vkCode == g_state.recorded_key.load()) {
        g_state.recorded_key_down.store(false);
        if (g_state.recorded_modifiers.load() == 0) {
            FinishRecording(2);
        }
    }
    return 1;
}

bool OpenClipboardWithRetry() {
    for (int attempt = 0; attempt < 10; ++attempt) {
        if (OpenClipboard(nullptr)) {
            return true;
        }
        Sleep(10);
    }
    return false;
}

bool EmptyClipboardSafely() {
    if (!OpenClipboardWithRetry()) {
        SetWindowsError("OpenClipboard");
        return false;
    }
    const BOOL emptied = EmptyClipboard();
    CloseClipboard();
    if (!emptied) {
        SetWindowsError("EmptyClipboard");
        return false;
    }
    return true;
}

std::wstring ReadClipboardText() {
    if (!OpenClipboardWithRetry()) {
        SetWindowsError("OpenClipboard");
        return {};
    }

    std::wstring text;
    HANDLE data = GetClipboardData(CF_UNICODETEXT);
    if (data != nullptr) {
        const auto* value = static_cast<const wchar_t*>(GlobalLock(data));
        if (value != nullptr) {
            text.assign(value);
            GlobalUnlock(data);
        }
    }
    CloseClipboard();
    return text;
}

std::wstring GetTextPatternSelection(IUIAutomationElement* element,
                                     bool* pattern_supported) {
    IUnknown* unknown = nullptr;
    if (FAILED(element->GetCurrentPattern(UIA_TextPatternId, &unknown)) ||
        unknown == nullptr) {
        return {};
    }
    IUIAutomationTextPattern* pattern = nullptr;
    const HRESULT query_result = unknown->QueryInterface(
        IID_PPV_ARGS(&pattern));
    unknown->Release();
    if (FAILED(query_result) || pattern == nullptr) {
        return {};
    }

    IUIAutomationTextRangeArray* ranges = nullptr;
    const HRESULT selection_result = pattern->GetSelection(&ranges);
    pattern->Release();
    if (FAILED(selection_result) || ranges == nullptr) {
        return {};
    }
    *pattern_supported = true;

    std::wstring selected;
    int count = 0;
    ranges->get_Length(&count);
    for (int index = 0; index < count; ++index) {
        IUIAutomationTextRange* range = nullptr;
        if (FAILED(ranges->GetElement(index, &range)) || range == nullptr) {
            continue;
        }
        BSTR value = nullptr;
        if (SUCCEEDED(range->GetText(-1, &value)) && value != nullptr &&
            SysStringLen(value) > 0) {
            if (!selected.empty()) {
                selected.push_back(L'\n');
            }
            selected.append(value, SysStringLen(value));
        }
        SysFreeString(value);
        range->Release();
    }
    ranges->Release();
    return selected;
}

std::wstring TryUiAutomationSelection(bool* selection_supported) {
    *selection_supported = false;
    IUIAutomation* automation = nullptr;
    if (FAILED(CoCreateInstance(CLSID_CUIAutomation, nullptr,
                                CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&automation))) ||
        automation == nullptr) {
        return {};
    }

    IUIAutomationElement* element = nullptr;
    if (FAILED(automation->GetFocusedElement(&element)) || element == nullptr) {
        automation->Release();
        return {};
    }

    IUIAutomationTreeWalker* walker = nullptr;
    automation->get_RawViewWalker(&walker);
    std::wstring selected;
    for (int depth = 0; depth < 8 && element != nullptr; ++depth) {
        bool pattern_supported = false;
        selected = GetTextPatternSelection(element, &pattern_supported);
        *selection_supported = *selection_supported || pattern_supported;
        if (!selected.empty()) {
            break;
        }
        if (walker == nullptr) {
            break;
        }
        IUIAutomationElement* parent = nullptr;
        walker->GetParentElement(element, &parent);
        element->Release();
        element = parent;
    }
    if (element != nullptr) {
        element->Release();
    }
    if (walker != nullptr) {
        walker->Release();
    }
    automation->Release();
    return selected;
}

void AppendKey(std::vector<INPUT>& input, WORD key, DWORD flags = 0) {
    INPUT event{};
    event.type = INPUT_KEYBOARD;
    event.ki.wVk = key;
    event.ki.dwFlags = flags;
    input.push_back(event);
}

bool SendCopyShortcut(unsigned int modifiers) {
    std::vector<INPUT> input;
    if (modifiers & MOD_CONTROL) {
        AppendKey(input, VK_CONTROL, KEYEVENTF_KEYUP);
    }
    if (modifiers & MOD_ALT) {
        AppendKey(input, VK_MENU, KEYEVENTF_KEYUP);
    }
    if (modifiers & MOD_SHIFT) {
        AppendKey(input, VK_SHIFT, KEYEVENTF_KEYUP);
    }
    if (modifiers & MOD_WIN) {
        AppendKey(input, VK_LWIN, KEYEVENTF_KEYUP);
        AppendKey(input, VK_RWIN, KEYEVENTF_KEYUP);
    }
    AppendKey(input, VK_CONTROL);
    AppendKey(input, 'C');
    AppendKey(input, 'C', KEYEVENTF_KEYUP);
    AppendKey(input, VK_CONTROL, KEYEVENTF_KEYUP);

    const UINT sent = SendInput(static_cast<UINT>(input.size()), input.data(),
                                sizeof(INPUT));
    if (sent != input.size()) {
        SetWindowsError("SendInput");
        return false;
    }
    return true;
}

bool WaitForClipboardChange(DWORD original_sequence) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(kClipboardTimeoutMs);
    while (std::chrono::steady_clock::now() < deadline) {
        if (GetClipboardSequenceNumber() != original_sequence) {
            return true;
        }
        Sleep(10);
    }
    return GetClipboardSequenceNumber() != original_sequence;
}

std::unique_ptr<ClipboardSnapshot> SnapshotClipboard() {
    auto snapshot = std::make_unique<ClipboardSnapshot>();
    if (!snapshot->Capture()) {
        SetError(
            "The clipboard could not be snapshotted without losing formats");
        return nullptr;
    }
    return snapshot;
}

void CaptureSelection(ULONGLONG requested_at) {
    g_state.capture_source.store(0);
    bool ui_automation_supported = false;
    std::wstring selected =
        TryUiAutomationSelection(&ui_automation_supported);
    if (!selected.empty()) {
        g_state.capture_source.store(1);
        if (g_state.callback != nullptr) {
            g_state.completed_capture_requested_at.store(requested_at);
            g_state.callback(selected.c_str(), g_state.callback_context);
        }
        return;
    }
    if (ui_automation_supported) {
        if (g_state.callback != nullptr) {
            g_state.completed_capture_requested_at.store(requested_at);
            g_state.callback(L"", g_state.callback_context);
        }
        return;
    }

    auto saved = SnapshotClipboard();
    if (saved == nullptr) {
        if (g_state.callback != nullptr) {
            g_state.completed_capture_requested_at.store(requested_at);
            g_state.callback(L"", g_state.callback_context);
        }
        return;
    }

    if (EmptyClipboardSafely()) {
        const DWORD sequence = GetClipboardSequenceNumber();
        if (SendCopyShortcut(g_state.modifiers.load()) &&
            WaitForClipboardChange(sequence)) {
            selected = ReadClipboardText();
            if (!selected.empty()) {
                g_state.capture_source.store(2);
            }
        }
    }

    if (!saved->Restore()) {
        SetError("The native input adapter could not restore the previous clipboard");
    }
    if (g_state.callback != nullptr) {
        g_state.completed_capture_requested_at.store(requested_at);
        g_state.callback(selected.c_str(), g_state.callback_context);
    }
}

LRESULT CALLBACK WindowProcedure(HWND window, UINT message, WPARAM wparam,
                                 LPARAM lparam) {
    switch (message) {
    case WM_HOTKEY:
        if (wparam == kHotkeyId && !g_state.recording.load() &&
            !g_state.ocr_dispatching.load()) {
            if (g_state.activation_callback != nullptr &&
                g_state.activation_callback(g_state.callback_context) != 0) {
                return 0;
            }
            CaptureSelection(GetTickCount64());
            return 0;
        }
        if (wparam == kOcrHotkeyId && !g_state.recording.load() &&
            g_state.ocr_handler != nullptr &&
            !g_state.ocr_dispatching.exchange(true)) {
            g_state.ocr_handler();
            g_state.ocr_dispatching.store(false);
            return 0;
        }
        break;
    case kCaptureMessage:
        if (!g_state.ocr_dispatching.load()) {
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
        g_state.ocr_handler = registration->handler;
        return 1;
    }
    case kUnregisterOcrHotkeyMessage:
        UnregisterHotKey(window, kOcrHotkeyId);
        g_state.ocr_handler = nullptr;
        return 1;
    case kRebindMessage: {
        const UINT previous_modifiers = g_state.modifiers.load();
        const UINT previous_key = g_state.virtual_key.load();
        UnregisterHotKey(window, kHotkeyId);
        if (RegisterHotKey(window, kHotkeyId,
                           static_cast<UINT>(wparam) | MOD_NOREPEAT,
                           static_cast<UINT>(lparam))) {
            g_state.modifiers.store(static_cast<UINT>(wparam));
            g_state.virtual_key.store(static_cast<UINT>(lparam));
            return 1;
        }
        SetWindowsError("RegisterHotKey");
        RegisterHotKey(window, kHotkeyId, previous_modifiers | MOD_NOREPEAT,
                       previous_key);
        return 0;
    }
    case kStartRecordingMessage: {
        if (g_state.recording.load()) {
            return 0;
        }
        HMODULE module = nullptr;
        GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&RecordingHook), &module);
        g_state.recording_callback =
            reinterpret_cast<ss_record_callback_t>(wparam);
        g_state.recording_context = reinterpret_cast<void*>(lparam);
        g_state.recorded_modifiers.store(0);
        g_state.recorded_chord_modifiers.store(0);
        g_state.recorded_key.store(0);
        g_state.recorded_key_down.store(false);
        g_state.recording_finishing.store(false);
        g_state.recording_hook =
            SetWindowsHookExW(WH_KEYBOARD_LL, RecordingHook, module, 0);
        if (g_state.recording_hook == nullptr) {
            SetWindowsError("SetWindowsHookEx");
            g_state.recording_callback = nullptr;
            g_state.recording_context = nullptr;
            return 0;
        }
        g_state.recording.store(true);
        return 1;
    }
    case kStopRecordingMessage:
        g_state.recording.store(false);
        if (g_state.recording_hook != nullptr) {
            UnhookWindowsHookEx(g_state.recording_hook);
            g_state.recording_hook = nullptr;
        }
        g_state.recording_callback = nullptr;
        g_state.recording_context = nullptr;
        return 1;
    case kRecordingEventMessage:
        if (g_state.recording_callback != nullptr) {
            g_state.recording_callback(
                static_cast<unsigned int>(wparam), LOWORD(lparam),
                HIWORD(lparam), g_state.recording_context);
        }
        return 0;
    case WM_CLOSE:
        SendMessageW(window, kStopRecordingMessage, 0, 0);
        UnregisterHotKey(window, kOcrHotkeyId);
        g_state.ocr_handler = nullptr;
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

void MessageLoop() {
    const HRESULT apartment = RoInitialize(RO_INIT_MULTITHREADED);
    if (FAILED(apartment)) {
        SetError("RoInitialize failed on the native input thread");
        {
            std::lock_guard lock(g_state.ready_mutex);
            g_state.start_succeeded = false;
            g_state.ready = true;
        }
        g_state.ready_changed.notify_one();
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
        g_state.window = window;
        succeeded = RegisterHotKey(window, kHotkeyId,
                                   g_state.modifiers.load() | MOD_NOREPEAT,
                                   g_state.virtual_key.load()) != FALSE;
        if (!succeeded) {
            SetWindowsError("RegisterHotKey");
            DestroyWindow(window);
            g_state.window = nullptr;
        }
    } else {
        SetWindowsError("CreateWindowEx");
    }

    {
        std::lock_guard lock(g_state.ready_mutex);
        g_state.start_succeeded = succeeded;
        g_state.ready = true;
    }
    g_state.ready_changed.notify_one();
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
    g_state.window = nullptr;
    RoUninitialize();
}
}  // namespace

namespace selectspeak::input {

DWORD RegisterOcrHotkey(unsigned int modifiers, unsigned int virtual_key,
                        OcrHotkeyHandler handler) {
    if (!g_state.running.load() || g_state.window == nullptr) {
        return ERROR_SERVICE_NOT_ACTIVE;
    }
    OcrHotkeyRegistration registration{modifiers, virtual_key, handler};
    const LRESULT registered = SendMessageW(
        g_state.window, kRegisterOcrHotkeyMessage, 0,
        reinterpret_cast<LPARAM>(&registration));
    if (!registered && registration.error == ERROR_SUCCESS) {
        return ERROR_GEN_FAILURE;
    }
    return registration.error;
}

void UnregisterOcrHotkey() {
    if (g_state.running.load() && g_state.window != nullptr) {
        SendMessageW(g_state.window, kUnregisterOcrHotkeyMessage, 0, 0);
    }
}

}  // namespace selectspeak::input

int ss_input_start(unsigned int modifiers, unsigned int virtual_key,
                          ss_capture_callback_t callback,
                          ss_activation_callback_t activation_callback,
                          void* context) {
    std::lock_guard lifecycle_lock(g_state.lifecycle_mutex);
    if (g_state.running.load()) {
        SetError("The native input adapter is already running");
        return 1;
    }
    if (callback == nullptr || virtual_key == 0) {
        SetError("A callback and virtual key are required");
        return 1;
    }

    g_state.callback = callback;
    g_state.activation_callback = activation_callback;
    g_state.callback_context = context;
    g_state.modifiers.store(modifiers);
    g_state.virtual_key.store(virtual_key);
    g_state.ready = false;
    g_state.start_succeeded = false;
    g_state.message_thread = std::thread(MessageLoop);
    {
        std::unique_lock ready_lock(g_state.ready_mutex);
        g_state.ready_changed.wait(ready_lock, [] { return g_state.ready; });
    }
    if (!g_state.start_succeeded) {
        g_state.message_thread.join();
        return 1;
    }
    g_state.running.store(true);
    return 0;
}

int ss_input_rebind(unsigned int modifiers, unsigned int virtual_key) {
    if (!g_state.running.load() || g_state.window == nullptr || virtual_key == 0) {
        SetError("The native input adapter is not running");
        return 1;
    }
    const LRESULT rebound = SendMessageW(g_state.window, kRebindMessage, modifiers,
                                         virtual_key);
    if (!rebound) {
        return 1;
    }
    return 0;
}

int ss_input_capture_now() {
    if (!g_state.running.load()) {
        SetError("The native input adapter is not running");
        return 1;
    }
    if (!PostMessageW(g_state.window, kCaptureMessage,
                      static_cast<WPARAM>(GetTickCount64()), 0)) {
        SetWindowsError("PostMessage");
        return 1;
    }
    return 0;
}

int ss_input_record_start(ss_record_callback_t callback, void* context) {
    if (!g_state.running.load() || g_state.window == nullptr || callback == nullptr) {
        SetError("The native input adapter is not ready to record a shortcut");
        return 1;
    }
    if (!SendMessageW(g_state.window, kStartRecordingMessage,
                      reinterpret_cast<WPARAM>(callback),
                      reinterpret_cast<LPARAM>(context))) {
        return 1;
    }
    return 0;
}

void ss_input_record_stop() {
    if (g_state.running.load() && g_state.window != nullptr) {
        SendMessageW(g_state.window, kStopRecordingMessage, 0, 0);
    }
}

void ss_input_stop() {
    // OCR registers on this message thread and must release its hotkey/overlay
    // before the window is destroyed.
    ss_ocr_stop();
    std::lock_guard lifecycle_lock(g_state.lifecycle_mutex);
    if (!g_state.running.exchange(false)) {
        return;
    }
    if (g_state.window != nullptr) {
        PostMessageW(g_state.window, WM_CLOSE, 0, 0);
    }
    if (g_state.message_thread.joinable()) {
        g_state.message_thread.join();
    }
    g_state.callback = nullptr;
    g_state.activation_callback = nullptr;
    g_state.callback_context = nullptr;
}

unsigned int ss_input_last_capture_source() {
    return g_state.capture_source.load();
}

unsigned long long ss_input_last_activation_time_ms() {
    return g_state.completed_capture_requested_at.load();
}

unsigned int ss_input_last_error(char* buffer, unsigned int length) {
    std::lock_guard lock(g_state.error_mutex);
    const unsigned int required =
        static_cast<unsigned int>(g_state.last_error.size() + 1);
    if (buffer != nullptr && length > 0) {
        const unsigned int count =
            required < length ? required : static_cast<unsigned int>(length);
        memcpy(buffer, g_state.last_error.c_str(), count - 1);
        buffer[count - 1] = '\0';
    }
    return required;
}
