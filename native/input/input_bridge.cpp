#include <windows.h>
#include <ole2.h>
#include <shlobj.h>
#include <uiautomation.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#ifdef SELECTSPEAK_INPUT_EXPORTS
#define INPUT_API extern "C" __declspec(dllexport)
#else
#define INPUT_API extern "C" __declspec(dllimport)
#endif

using capture_callback_t = void(__cdecl*)(const wchar_t*, void*);
using activation_callback_t = int(__cdecl*)(void*);
using record_callback_t =
    void(__cdecl*)(unsigned int, unsigned int, unsigned int, void*);

namespace {
constexpr int kHotkeyId = 1;
constexpr UINT kRebindMessage = WM_APP + 1;
constexpr UINT kStartRecordingMessage = WM_APP + 2;
constexpr UINT kStopRecordingMessage = WM_APP + 3;
constexpr UINT kRecordingEventMessage = WM_APP + 4;
constexpr DWORD kClipboardTimeoutMs = 1000;
constexpr wchar_t kWindowClass[] = L"SelectSpeakNativeInputWindow";

struct State {
    std::mutex lifecycle_mutex;
    std::mutex request_mutex;
    std::condition_variable request_changed;
    bool capture_requested = false;
    ULONGLONG capture_requested_at = 0;
    bool worker_stopping = false;
    std::thread message_thread;
    std::thread worker_thread;

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
    HANDLE clipboard_changed = nullptr;
    capture_callback_t callback = nullptr;
    activation_callback_t activation_callback = nullptr;
    void* callback_context = nullptr;
    HHOOK recording_hook = nullptr;
    record_callback_t recording_callback = nullptr;
    void* recording_context = nullptr;
    std::atomic<bool> recording{false};
    std::atomic<bool> recording_finishing{false};
    std::atomic<unsigned int> recorded_modifiers{0};
    std::atomic<unsigned int> recorded_chord_modifiers{0};
    std::atomic<unsigned int> recorded_key{0};
    std::atomic<bool> recorded_key_down{false};

    std::mutex error_mutex;
    std::string last_error;
};

State g_state;

HRESULT DuplicateMedium(const FORMATETC& format, const STGMEDIUM& source,
                        STGMEDIUM* result) {
    if (result == nullptr) {
        return E_POINTER;
    }
    *result = {};
    result->tymed = source.tymed;
    switch (source.tymed) {
    case TYMED_HGLOBAL:
        result->hGlobal = static_cast<HGLOBAL>(
            OleDuplicateData(source.hGlobal, format.cfFormat, 0));
        break;
    case TYMED_GDI:
        result->hBitmap = static_cast<HBITMAP>(
            OleDuplicateData(source.hBitmap, format.cfFormat, 0));
        break;
    case TYMED_MFPICT:
        result->hMetaFilePict = static_cast<HMETAFILEPICT>(
            OleDuplicateData(source.hMetaFilePict, format.cfFormat, 0));
        break;
    case TYMED_ENHMF:
        result->hEnhMetaFile = static_cast<HENHMETAFILE>(
            OleDuplicateData(source.hEnhMetaFile, format.cfFormat, 0));
        break;
    case TYMED_FILE: {
        if (source.lpszFileName == nullptr) {
            return DV_E_TYMED;
        }
        const size_t bytes =
            (wcslen(source.lpszFileName) + 1) * sizeof(wchar_t);
        result->lpszFileName = static_cast<LPOLESTR>(CoTaskMemAlloc(bytes));
        if (result->lpszFileName != nullptr) {
            memcpy(result->lpszFileName, source.lpszFileName, bytes);
        }
        break;
    }
    case TYMED_ISTREAM: {
        if (source.pstm == nullptr) {
            return DV_E_TYMED;
        }
        HRESULT status = CreateStreamOnHGlobal(nullptr, TRUE, &result->pstm);
        if (FAILED(status)) {
            return status;
        }
        LARGE_INTEGER zero{};
        source.pstm->Seek(zero, STREAM_SEEK_SET, nullptr);
        ULARGE_INTEGER maximum{};
        maximum.QuadPart = static_cast<ULONGLONG>(-1);
        status = source.pstm->CopyTo(result->pstm, maximum, nullptr, nullptr);
        result->pstm->Seek(zero, STREAM_SEEK_SET, nullptr);
        if (FAILED(status)) {
            result->pstm->Release();
            result->pstm = nullptr;
            return status;
        }
        return S_OK;
    }
    case TYMED_ISTORAGE: {
        if (source.pstg == nullptr) {
            return DV_E_TYMED;
        }
        ILockBytes* bytes = nullptr;
        HRESULT status = CreateILockBytesOnHGlobal(nullptr, TRUE, &bytes);
        if (SUCCEEDED(status)) {
            status = StgCreateDocfileOnILockBytes(
                bytes, STGM_CREATE | STGM_READWRITE | STGM_SHARE_EXCLUSIVE, 0,
                &result->pstg);
        }
        if (SUCCEEDED(status)) {
            status = source.pstg->CopyTo(0, nullptr, nullptr, result->pstg);
        }
        if (SUCCEEDED(status)) {
            status = result->pstg->Commit(STGC_DEFAULT);
        }
        if (bytes != nullptr) {
            bytes->Release();
        }
        if (FAILED(status)) {
            if (result->pstg != nullptr) {
                result->pstg->Release();
                result->pstg = nullptr;
            }
            return status;
        }
        return S_OK;
    }
    default:
        return DV_E_TYMED;
    }
    if (result->hGlobal == nullptr) {
        *result = {};
        return E_OUTOFMEMORY;
    }
    return S_OK;
}

FORMATETC CopyFormat(const FORMATETC& source) {
    FORMATETC result = source;
    result.ptd = nullptr;
    if (source.ptd != nullptr && source.ptd->tdSize >= sizeof(DVTARGETDEVICE)) {
        result.ptd = static_cast<DVTARGETDEVICE*>(
            CoTaskMemAlloc(source.ptd->tdSize));
        if (result.ptd != nullptr) {
            memcpy(result.ptd, source.ptd, source.ptd->tdSize);
        }
    }
    return result;
}

struct ClipboardEntry {
    FORMATETC format{};
    STGMEDIUM medium{};

    ~ClipboardEntry() {
        if (format.ptd != nullptr) {
            CoTaskMemFree(format.ptd);
        }
        ReleaseStgMedium(&medium);
    }
};

class ClipboardSnapshot final : public IDataObject {
public:
    HRESULT Add(IDataObject* source, const FORMATETC& format) {
        auto entry = std::make_unique<ClipboardEntry>();
        entry->format = CopyFormat(format);
        STGMEDIUM medium{};
        HRESULT result =
            source->GetData(const_cast<FORMATETC*>(&format), &medium);
        if (FAILED(result)) {
            return result;
        }
        result = DuplicateMedium(format, medium, &entry->medium);
        ReleaseStgMedium(&medium);
        if (FAILED(result)) {
            return result;
        }
        entries_.push_back(std::move(entry));
        return S_OK;
    }

    bool empty() const { return entries_.empty(); }

    bool Restore() const {
        bool opened = false;
        for (int attempt = 0; attempt < 10; ++attempt) {
            if (OpenClipboard(nullptr)) {
                opened = true;
                break;
            }
            Sleep(10);
        }
        if (!opened) {
            return false;
        }
        if (!EmptyClipboard()) {
            CloseClipboard();
            return false;
        }

        bool restored_any = entries_.empty();
        for (const auto& entry : entries_) {
            if (entry->medium.tymed != TYMED_HGLOBAL &&
                entry->medium.tymed != TYMED_GDI &&
                entry->medium.tymed != TYMED_MFPICT &&
                entry->medium.tymed != TYMED_ENHMF) {
                continue;
            }
            STGMEDIUM copy{};
            if (FAILED(DuplicateMedium(entry->format, entry->medium, &copy))) {
                continue;
            }
            if (SetClipboardData(entry->format.cfFormat, copy.hGlobal) != nullptr) {
                restored_any = true;
                copy.tymed = TYMED_NULL;
                copy.hGlobal = nullptr;
            }
            ReleaseStgMedium(&copy);
        }
        CloseClipboard();
        return restored_any;
    }

    STDMETHODIMP QueryInterface(REFIID iid, void** object) override {
        if (object == nullptr) {
            return E_POINTER;
        }
        if (iid == IID_IUnknown || iid == IID_IDataObject) {
            *object = static_cast<IDataObject*>(this);
            AddRef();
            return S_OK;
        }
        *object = nullptr;
        return E_NOINTERFACE;
    }

    STDMETHODIMP_(ULONG) AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&references_));
    }

    STDMETHODIMP_(ULONG) Release() override {
        const ULONG remaining =
            static_cast<ULONG>(InterlockedDecrement(&references_));
        if (remaining == 0) {
            delete this;
        }
        return remaining;
    }

    STDMETHODIMP GetData(FORMATETC* requested, STGMEDIUM* result) override {
        if (requested == nullptr || result == nullptr) {
            return E_POINTER;
        }
        for (const auto& entry : entries_) {
            if (Matches(*requested, entry->format)) {
                return DuplicateMedium(entry->format, entry->medium, result);
            }
        }
        return DV_E_FORMATETC;
    }

    STDMETHODIMP GetDataHere(FORMATETC*, STGMEDIUM*) override {
        return E_NOTIMPL;
    }

    STDMETHODIMP QueryGetData(FORMATETC* requested) override {
        if (requested == nullptr) {
            return E_POINTER;
        }
        for (const auto& entry : entries_) {
            if (Matches(*requested, entry->format)) {
                return S_OK;
            }
        }
        return DV_E_FORMATETC;
    }

    STDMETHODIMP GetCanonicalFormatEtc(FORMATETC*, FORMATETC* output) override {
        if (output != nullptr) {
            output->ptd = nullptr;
        }
        return E_NOTIMPL;
    }

    STDMETHODIMP SetData(FORMATETC*, STGMEDIUM*, BOOL) override {
        return E_NOTIMPL;
    }

    STDMETHODIMP EnumFormatEtc(DWORD direction,
                               IEnumFORMATETC** enumerator) override {
        if (enumerator == nullptr) {
            return E_POINTER;
        }
        *enumerator = nullptr;
        if (direction != DATADIR_GET) {
            return E_NOTIMPL;
        }
        std::vector<FORMATETC> formats;
        formats.reserve(entries_.size());
        for (const auto& entry : entries_) {
            formats.push_back(entry->format);
        }
        return SHCreateStdEnumFmtEtc(static_cast<UINT>(formats.size()),
                                     formats.data(), enumerator);
    }

    STDMETHODIMP DAdvise(FORMATETC*, DWORD, IAdviseSink*, DWORD*) override {
        return OLE_E_ADVISENOTSUPPORTED;
    }

    STDMETHODIMP DUnadvise(DWORD) override {
        return OLE_E_ADVISENOTSUPPORTED;
    }

    STDMETHODIMP EnumDAdvise(IEnumSTATDATA**) override {
        return OLE_E_ADVISENOTSUPPORTED;
    }

private:
    static bool Matches(const FORMATETC& requested, const FORMATETC& available) {
        return requested.cfFormat == available.cfFormat &&
               requested.dwAspect == available.dwAspect &&
               requested.lindex == available.lindex &&
               (requested.tymed & available.tymed) != 0;
    }

    volatile LONG references_ = 1;
    std::vector<std::unique_ptr<ClipboardEntry>> entries_;
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

void QueueCapture() {
    std::lock_guard lock(g_state.request_mutex);
    if (!g_state.worker_stopping) {
        if (!g_state.capture_requested) {
            g_state.capture_requested_at = GetTickCount64();
        }
        g_state.capture_requested = true;
        g_state.request_changed.notify_one();
    }
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
        const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - std::chrono::steady_clock::now());
        const DWORD wait_ms = static_cast<DWORD>(
            remaining.count() > 0 ? remaining.count() : 1);
        WaitForSingleObject(g_state.clipboard_changed, wait_ms);
        ResetEvent(g_state.clipboard_changed);
    }
    return GetClipboardSequenceNumber() != original_sequence;
}

ClipboardSnapshot* SnapshotClipboard() {
    IDataObject* source = nullptr;
    if (FAILED(OleGetClipboard(&source)) || source == nullptr) {
        SetError("OleGetClipboard could not access the current clipboard");
        return nullptr;
    }

    auto* snapshot = new ClipboardSnapshot();
    IEnumFORMATETC* formats = nullptr;
    const HRESULT enum_result = source->EnumFormatEtc(DATADIR_GET, &formats);
    if (SUCCEEDED(enum_result) && formats != nullptr) {
        FORMATETC format{};
        while (formats->Next(1, &format, nullptr) == S_OK) {
            const HRESULT add_result = snapshot->Add(source, format);
            if (FAILED(add_result)) {
                SetError("Clipboard format snapshot failed with HRESULT " +
                         std::to_string(static_cast<unsigned long>(add_result)));
            }
            if (format.ptd != nullptr) {
                CoTaskMemFree(format.ptd);
                format.ptd = nullptr;
            }
        }
        formats->Release();
    } else {
        SetError("Clipboard format enumeration failed with HRESULT " +
                 std::to_string(static_cast<unsigned long>(enum_result)));
    }
    source->Release();
    if (snapshot->empty()) {
        SetError("The clipboard snapshot contained no transferable formats");
    }
    return snapshot;
}

void RestoreClipboard(ClipboardSnapshot* saved) {
    if (saved == nullptr) {
        return;
    }
    if (!saved->Restore()) {
        SetError("The native input adapter could not restore the previous clipboard");
    }
    saved->Release();
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

    ClipboardSnapshot* saved = SnapshotClipboard();
    if (saved == nullptr) {
        if (g_state.callback != nullptr) {
            g_state.completed_capture_requested_at.store(requested_at);
            g_state.callback(L"", g_state.callback_context);
        }
        return;
    }

    if (EmptyClipboardSafely()) {
        const DWORD sequence = GetClipboardSequenceNumber();
        ResetEvent(g_state.clipboard_changed);
        if (SendCopyShortcut(g_state.modifiers.load()) &&
            WaitForClipboardChange(sequence)) {
            selected = ReadClipboardText();
            if (!selected.empty()) {
                g_state.capture_source.store(2);
            }
        }
    }

    RestoreClipboard(saved);
    if (g_state.callback != nullptr) {
        g_state.completed_capture_requested_at.store(requested_at);
        g_state.callback(selected.c_str(), g_state.callback_context);
    }
}

void CaptureWorker() {
    const HRESULT ole_result = OleInitialize(nullptr);
    if (FAILED(ole_result)) {
        SetError("OleInitialize failed on the capture worker");
    }

    while (true) {
        ULONGLONG requested_at = 0;
        {
            std::unique_lock lock(g_state.request_mutex);
            g_state.request_changed.wait(lock, [] {
                return g_state.capture_requested || g_state.worker_stopping;
            });
            if (g_state.worker_stopping) {
                break;
            }
            requested_at = g_state.capture_requested_at;
            g_state.capture_requested = false;
        }
        CaptureSelection(requested_at);
    }

    if (SUCCEEDED(ole_result)) {
        OleUninitialize();
    }
}

LRESULT CALLBACK WindowProcedure(HWND window, UINT message, WPARAM wparam,
                                 LPARAM lparam) {
    switch (message) {
    case WM_HOTKEY:
        if (wparam == kHotkeyId && !g_state.recording.load()) {
            if (g_state.activation_callback != nullptr &&
                g_state.activation_callback(g_state.callback_context) != 0) {
                return 0;
            }
            QueueCapture();
            return 0;
        }
        break;
    case WM_CLIPBOARDUPDATE:
        SetEvent(g_state.clipboard_changed);
        return 0;
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
            reinterpret_cast<record_callback_t>(wparam);
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
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

void MessageLoop() {
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
        AddClipboardFormatListener(window);
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
        return;
    }

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    RemoveClipboardFormatListener(window);
    UnregisterHotKey(window, kHotkeyId);
    g_state.window = nullptr;
}
}  // namespace

INPUT_API int input_start(unsigned int modifiers, unsigned int virtual_key,
                          capture_callback_t callback,
                          activation_callback_t activation_callback,
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
    g_state.capture_requested = false;
    g_state.worker_stopping = false;
    g_state.clipboard_changed = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (g_state.clipboard_changed == nullptr) {
        SetWindowsError("CreateEvent");
        return 1;
    }

    g_state.worker_thread = std::thread(CaptureWorker);
    g_state.message_thread = std::thread(MessageLoop);
    {
        std::unique_lock ready_lock(g_state.ready_mutex);
        g_state.ready_changed.wait(ready_lock, [] { return g_state.ready; });
    }
    if (!g_state.start_succeeded) {
        {
            std::lock_guard request_lock(g_state.request_mutex);
            g_state.worker_stopping = true;
        }
        g_state.request_changed.notify_one();
        g_state.message_thread.join();
        g_state.worker_thread.join();
        CloseHandle(g_state.clipboard_changed);
        g_state.clipboard_changed = nullptr;
        return 1;
    }
    g_state.running.store(true);
    return 0;
}

INPUT_API int input_rebind(unsigned int modifiers, unsigned int virtual_key) {
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

INPUT_API int input_capture_now() {
    if (!g_state.running.load()) {
        SetError("The native input adapter is not running");
        return 1;
    }
    QueueCapture();
    return 0;
}

INPUT_API int input_record_start(record_callback_t callback, void* context) {
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

INPUT_API void input_record_stop() {
    if (g_state.running.load() && g_state.window != nullptr) {
        SendMessageW(g_state.window, kStopRecordingMessage, 0, 0);
    }
}

INPUT_API void input_stop() {
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
    {
        std::lock_guard request_lock(g_state.request_mutex);
        g_state.worker_stopping = true;
    }
    g_state.request_changed.notify_one();
    if (g_state.worker_thread.joinable()) {
        g_state.worker_thread.join();
    }
    CloseHandle(g_state.clipboard_changed);
    g_state.clipboard_changed = nullptr;
    g_state.callback = nullptr;
    g_state.activation_callback = nullptr;
    g_state.callback_context = nullptr;
}

INPUT_API unsigned int input_last_capture_source() {
    return g_state.capture_source.load();
}

INPUT_API unsigned long long input_last_activation_time_ms() {
    return g_state.completed_capture_requested_at.load();
}

INPUT_API unsigned int input_last_error(char* buffer, unsigned int length) {
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
