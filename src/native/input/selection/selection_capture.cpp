#include "selection_capture.h"
#include "selection_policy.h"

#include <windows.h>
#include <ole2.h>
#include <uiautomation.h>
#include <winrt/base.h>

#include <chrono>
#include <cstdint>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace selectspeak::input {
namespace {
thread_local winrt::com_ptr<IUIAutomation> g_automation;
constexpr DWORD kWindowMessageClipboardTimeoutMs = 50;
constexpr DWORD kSyntheticClipboardTimeoutMs = 100;
constexpr DWORD kCopyMessageTimeoutMs = 100;
constexpr DWORD kClipboardPollIntervalMs = 5;
constexpr int kMaximumSelectionCharacters = 1'000'000;

enum class NativeSelectionState {
    Unsupported,
    Empty,
    Selected,
};

struct ClipboardCaptureAttempt {
    std::wstring text;
    bool clipboard_cleared = false;
    bool action_sent = false;
    bool clipboard_changed = false;
    DWORD resulting_sequence = 0;
    long long duration_ms = 0;
};

long long ElapsedMs(std::chrono::steady_clock::time_point started)
{
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now() - started)
        .count();
}

const char* NativeSelectionName(NativeSelectionState state)
{
    switch (state) {
    case NativeSelectionState::Empty:
        return "empty";
    case NativeSelectionState::Selected:
        return "selected";
    default:
        return "unsupported";
    }
}

std::string WindowsError(const char* action, DWORD code = GetLastError())
{
    return std::string(action) + " failed with Windows error " +
           std::to_string(code);
}

bool OpenClipboardWithRetry(HWND owner)
{
    for (int attempt = 0; attempt < 10; ++attempt) {
        if (OpenClipboard(owner)) {
            return true;
        }
        Sleep(10);
    }
    return false;
}

class ClipboardScope {
public:
    explicit ClipboardScope(HWND owner) : opened_(OpenClipboardWithRetry(owner)) {}
    ClipboardScope(const ClipboardScope&) = delete;
    ClipboardScope& operator=(const ClipboardScope&) = delete;
    ~ClipboardScope()
    {
        if (opened_) {
            CloseClipboard();
        }
    }
    explicit operator bool() const { return opened_; }

private:
    bool opened_ = false;
};

class ClipboardOwnerWindow {
public:
    ClipboardOwnerWindow()
        : window_(CreateWindowExW(0, L"STATIC", L"", 0, 0, 0, 0, 0,
                                  HWND_MESSAGE, nullptr,
                                  GetModuleHandleW(nullptr), nullptr))
    {
    }
    ClipboardOwnerWindow(const ClipboardOwnerWindow&) = delete;
    ClipboardOwnerWindow& operator=(const ClipboardOwnerWindow&) = delete;
    ~ClipboardOwnerWindow()
    {
        if (window_ != nullptr) {
            DestroyWindow(window_);
        }
    }
    HWND get() const { return window_; }

private:
    HWND window_ = nullptr;
};

class KernelHandle {
public:
    explicit KernelHandle(HANDLE handle = nullptr) : handle_(handle) {}
    KernelHandle(const KernelHandle&) = delete;
    KernelHandle& operator=(const KernelHandle&) = delete;
    ~KernelHandle()
    {
        if (handle_ != nullptr) {
            CloseHandle(handle_);
        }
    }
    HANDLE get() const { return handle_; }
    HANDLE* put()
    {
        if (handle_ != nullptr) {
            CloseHandle(handle_);
        }
        handle_ = nullptr;
        return &handle_;
    }
    explicit operator bool() const { return handle_ != nullptr; }

private:
    HANDLE handle_ = nullptr;
};

bool IsUnsupportedClipboardFormat(UINT format)
{
    return format == CF_OWNERDISPLAY || format == CF_DSPTEXT ||
           format == CF_DSPBITMAP || format == CF_DSPMETAFILEPICT ||
           format == CF_DSPENHMETAFILE ||
           (format >= CF_PRIVATEFIRST && format <= CF_PRIVATELAST) ||
           (format >= CF_GDIOBJFIRST && format <= CF_GDIOBJLAST);
}

HANDLE DuplicateClipboardData(UINT format, HANDLE source)
{
    if (format == CF_ENHMETAFILE) {
        return CopyEnhMetaFileW(static_cast<HENHMETAFILE>(source), nullptr);
    }
    return OleDuplicateData(source, static_cast<CLIPFORMAT>(format),
                            GMEM_MOVEABLE);
}

void ReleaseClipboardData(UINT format, HANDLE data)
{
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
    UINT format;
    HANDLE data;

    ClipboardEntry(UINT entry_format, HANDLE entry_data)
        : format(entry_format), data(entry_data)
    {
    }
    ClipboardEntry(const ClipboardEntry&) = delete;
    ClipboardEntry& operator=(const ClipboardEntry&) = delete;
    ClipboardEntry(ClipboardEntry&& other) noexcept
        : format(other.format), data(other.data)
    {
        other.data = nullptr;
    }
    ClipboardEntry& operator=(ClipboardEntry&&) = delete;
    ~ClipboardEntry() { ReleaseClipboardData(format, data); }
};

class ClipboardSnapshot {
public:
    bool Capture(HWND owner)
    {
        ClipboardScope clipboard(owner);
        if (!clipboard) {
            return false;
        }
        bool captured_all = true;
        UINT format = 0;
        while ((format = EnumClipboardFormats(format)) != 0) {
            if (IsUnsupportedClipboardFormat(format)) {
                captured_all = false;
                continue;
            }
            HANDLE source = GetClipboardData(format);
            HANDLE duplicate = source == nullptr
                                   ? nullptr
                                   : DuplicateClipboardData(format, source);
            if (duplicate != nullptr) {
                entries_.emplace_back(format, duplicate);
            } else {
                captured_all = false;
            }
        }
        complete_ = captured_all;
        return true;
    }

    bool Restore(HWND owner)
    {
        ClipboardScope clipboard(owner);
        if (!clipboard) {
            return false;
        }
        if (!EmptyClipboard()) {
            return false;
        }
        bool restored_all = true;
        for (auto& entry : entries_) {
            if (SetClipboardData(entry.format, entry.data) == nullptr) {
                restored_all = false;
            } else {
                entry.data = nullptr;
            }
        }
        return restored_all;
    }

    bool complete() const { return complete_; }

private:
    std::vector<ClipboardEntry> entries_;
    bool complete_ = true;
};

struct UiSelection {
    std::wstring text;
};

IUIAutomation* AutomationForThread()
{
    if (!g_automation) {
        winrt::com_ptr<IUIAutomation> created;
        if (SUCCEEDED(CoCreateInstance(CLSID_CUIAutomation, nullptr,
                                       CLSCTX_INPROC_SERVER,
                                       IID_PPV_ARGS(created.put())))) {
            g_automation = std::move(created);
        }
    }
    return g_automation.get();
}

std::wstring GetTextPatternSelection(IUIAutomationElement* element)
{
    winrt::com_ptr<IUnknown> unknown;
    if (FAILED(element->GetCurrentPattern(UIA_TextPatternId, unknown.put())) ||
        !unknown) {
        return {};
    }
    winrt::com_ptr<IUIAutomationTextPattern> pattern;
    if (FAILED(unknown->QueryInterface(IID_PPV_ARGS(pattern.put()))) ||
        !pattern) {
        return {};
    }

    winrt::com_ptr<IUIAutomationTextRangeArray> ranges;
    if (FAILED(pattern->GetSelection(ranges.put())) || !ranges) {
        return {};
    }
    std::wstring selected;
    int count = 0;
    if (FAILED(ranges->get_Length(&count))) {
        return {};
    }
    for (int index = 0; index < count; ++index) {
        winrt::com_ptr<IUIAutomationTextRange> range;
        if (FAILED(ranges->GetElement(index, range.put())) || !range) {
            continue;
        }
        BSTR value = nullptr;
        const int remaining = kMaximumSelectionCharacters -
                              static_cast<int>(selected.size());
        if (remaining <= 0) {
            break;
        }
        if (SUCCEEDED(range->GetText(remaining, &value)) && value != nullptr &&
            SysStringLen(value) > 0) {
            if (!selected.empty()) {
                selected.push_back(L'\n');
            }
            selected.append(value, SysStringLen(value));
        }
        SysFreeString(value);
    }
    return selected;
}

UiSelection TryGetUiSelection()
{
    IUIAutomation* automation = AutomationForThread();
    if (automation == nullptr) {
        return {};
    }

    winrt::com_ptr<IUIAutomationElement> focused;
    if (FAILED(automation->GetFocusedElement(focused.put())) || !focused) {
        return {};
    }

    winrt::com_ptr<IUIAutomationTreeWalker> walker;
    automation->get_RawViewWalker(walker.put());
    UiSelection result;
    winrt::com_ptr<IUIAutomationElement> element;
    element.copy_from(focused.get());
    for (int depth = 0; depth < 8 && element; ++depth) {
        result.text = GetTextPatternSelection(element.get());
        if (!result.text.empty() || !walker) {
            break;
        }
        winrt::com_ptr<IUIAutomationElement> parent;
        walker->GetParentElement(element.get(), parent.put());
        element = std::move(parent);
    }

    if (result.text.empty()) {
        VARIANT available{};
        available.vt = VT_BOOL;
        available.boolVal = VARIANT_TRUE;
        winrt::com_ptr<IUIAutomationCondition> condition;
        if (SUCCEEDED(automation->CreatePropertyCondition(
                UIA_IsTextPatternAvailablePropertyId, available,
                condition.put())) &&
            condition) {
            winrt::com_ptr<IUIAutomationElementArray> descendants;
            if (SUCCEEDED(focused->FindAll(TreeScope_Descendants,
                                           condition.get(),
                                           descendants.put())) &&
                descendants) {
                int count = 0;
                descendants->get_Length(&count);
                for (int index = 0; index < std::min(count, 16); ++index) {
                    winrt::com_ptr<IUIAutomationElement> descendant;
                    if (SUCCEEDED(descendants->GetElement(
                            index, descendant.put())) &&
                        descendant) {
                        result.text =
                            GetTextPatternSelection(descendant.get());
                        if (!result.text.empty()) {
                            break;
                        }
                    }
                }
            }
        }
    }
    return result;
}

HWND GetFocusedWindow(HWND foreground)
{
    if (foreground == nullptr) {
        return nullptr;
    }

    const DWORD thread_id = GetWindowThreadProcessId(foreground, nullptr);
    GUITHREADINFO info{};
    info.cbSize = sizeof(info);
    if (thread_id != 0 && GetGUIThreadInfo(thread_id, &info) &&
        info.hwndFocus != nullptr) {
        return info.hwndFocus;
    }
    return foreground;
}

std::string WindowClassName(HWND window)
{
    char class_name[128]{};
    if (window == nullptr ||
        GetClassNameA(window, class_name, _countof(class_name)) == 0) {
        return "unavailable";
    }
    return class_name;
}

DWORD ProcessIntegrityLevel(DWORD process_id)
{
    KernelHandle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                                     process_id));
    if (!process) {
        return 0;
    }
    KernelHandle token;
    if (!OpenProcessToken(process.get(), TOKEN_QUERY, token.put())) {
        return 0;
    }
    DWORD required = 0;
    GetTokenInformation(token.get(), TokenIntegrityLevel, nullptr, 0, &required);
    std::vector<std::uint8_t> storage(required);
    DWORD level = 0;
    if (required > 0 && GetTokenInformation(
                            token.get(), TokenIntegrityLevel, storage.data(),
                            required, &required)) {
        const auto* label =
            reinterpret_cast<const TOKEN_MANDATORY_LABEL*>(storage.data());
        const DWORD count = *GetSidSubAuthorityCount(label->Label.Sid);
        level = *GetSidSubAuthority(label->Label.Sid, count - 1);
    }
    return level;
}

bool TargetHasHigherIntegrity(HWND window)
{
    DWORD target_process = 0;
    GetWindowThreadProcessId(window, &target_process);
    const DWORD current = ProcessIntegrityLevel(GetCurrentProcessId());
    const DWORD target = ProcessIntegrityLevel(target_process);
    return current != 0 && target != 0 && target > current;
}

bool IsNativeTextControl(HWND window)
{
    wchar_t class_name[64]{};
    const int length = GetClassNameW(window, class_name, _countof(class_name));
    if (length == 0) {
        return false;
    }
    return _wcsicmp(class_name, L"Edit") == 0 ||
           _wcsnicmp(class_name, L"RichEdit", 8) == 0;
}

NativeSelectionState GetNativeSelectionState(HWND window)
{
    if (window == nullptr || !IsNativeTextControl(window)) {
        return NativeSelectionState::Unsupported;
    }

    DWORD start = 0;
    DWORD end = 0;
    DWORD_PTR ignored = 0;
    if (!SendMessageTimeoutW(window, EM_GETSEL,
                             reinterpret_cast<WPARAM>(&start),
                             reinterpret_cast<LPARAM>(&end),
                             SMTO_ABORTIFHUNG | SMTO_BLOCK,
                             kCopyMessageTimeoutMs, &ignored)) {
        return NativeSelectionState::Unsupported;
    }
    // Standard text controls can report an empty selection authoritatively.
    return start == end ? NativeSelectionState::Empty
                        : NativeSelectionState::Selected;
}

bool EmptyClipboardSafely(HWND owner, std::string& error)
{
    ClipboardScope clipboard(owner);
    if (!clipboard) {
        error = WindowsError("OpenClipboard");
        return false;
    }
    const BOOL emptied = EmptyClipboard();
    const DWORD code = emptied ? ERROR_SUCCESS : GetLastError();
    if (!emptied) {
        error = WindowsError("EmptyClipboard", code);
        return false;
    }
    return true;
}

std::wstring ReadClipboardText(HWND owner, std::string& error)
{
    ClipboardScope clipboard(owner);
    if (!clipboard) {
        error = WindowsError("OpenClipboard");
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
    return text;
}

void AppendKey(std::vector<INPUT>& input, WORD key, DWORD flags = 0)
{
    INPUT event{};
    event.type = INPUT_KEYBOARD;
    event.ki.wVk = key;
    event.ki.dwFlags = flags;
    input.push_back(event);
}

bool KeyIsDown(int virtual_key)
{
    return (GetAsyncKeyState(virtual_key) & 0x8000) != 0;
}

void AppendModifierKeyUps(std::vector<INPUT>& input, WORD generic,
                          WORD left, WORD right)
{
    bool released_side = false;
    if (KeyIsDown(left)) {
        AppendKey(input, left, KEYEVENTF_KEYUP);
        released_side = true;
    }
    if (KeyIsDown(right)) {
        AppendKey(input, right, KEYEVENTF_KEYUP);
        released_side = true;
    }
    if (!released_side && KeyIsDown(generic)) {
        AppendKey(input, generic, KEYEVENTF_KEYUP);
    }
}

bool SendCopyMessage(HWND window, bool& delivered, DWORD_PTR& handler_result)
{
    delivered = false;
    handler_result = 0;
    if (window == nullptr) {
        return false;
    }
    delivered = SendMessageTimeoutW(window, WM_COPY, 0, 0,
                                    SMTO_ABORTIFHUNG | SMTO_BLOCK,
                                    kCopyMessageTimeoutMs,
                                    &handler_result) != 0;
    return delivered && handler_result != 0;
}

bool SendCopyShortcut(unsigned int modifiers, unsigned int virtual_key,
                      std::string& error)
{
    std::vector<INPUT> input;
    // Neutralize the complete registered chord in the same input batch as the
    // copy shortcut so its physical state cannot modify Ctrl+C.
    if (virtual_key != 0) {
        AppendKey(input, static_cast<WORD>(virtual_key), KEYEVENTF_KEYUP);
    }
    if (modifiers & MOD_WIN) {
        if (KeyIsDown(VK_LWIN)) {
            AppendKey(input, VK_LWIN, KEYEVENTF_KEYUP);
        }
        if (KeyIsDown(VK_RWIN)) {
            AppendKey(input, VK_RWIN, KEYEVENTF_KEYUP);
        }
    }
    if (modifiers & MOD_SHIFT) {
        AppendModifierKeyUps(input, VK_SHIFT, VK_LSHIFT, VK_RSHIFT);
    }
    if (modifiers & MOD_ALT) {
        const bool right_alt = KeyIsDown(VK_RMENU);
        AppendModifierKeyUps(input, VK_MENU, VK_LMENU, VK_RMENU);
        if (right_alt && !(modifiers & MOD_CONTROL)) {
            AppendModifierKeyUps(input, VK_CONTROL, VK_LCONTROL, VK_RCONTROL);
        }
    }
    if (modifiers & MOD_CONTROL) {
        AppendModifierKeyUps(input, VK_CONTROL, VK_LCONTROL, VK_RCONTROL);
    }
    AppendKey(input, VK_CONTROL);
    AppendKey(input, 'C');
    AppendKey(input, 'C', KEYEVENTF_KEYUP);
    AppendKey(input, VK_CONTROL, KEYEVENTF_KEYUP);

    const UINT sent = SendInput(static_cast<UINT>(input.size()), input.data(),
                                sizeof(INPUT));
    if (sent != input.size()) {
        std::vector<INPUT> cleanup;
        AppendKey(cleanup, 'C', KEYEVENTF_KEYUP);
        AppendKey(cleanup, VK_CONTROL, KEYEVENTF_KEYUP);
        if (virtual_key != 0) {
            AppendKey(cleanup, static_cast<WORD>(virtual_key), KEYEVENTF_KEYUP);
        }
        SendInput(static_cast<UINT>(cleanup.size()), cleanup.data(),
                  sizeof(INPUT));
        error = WindowsError("SendInput");
        return false;
    }
    return true;
}

bool WaitForClipboardText(DWORD original_sequence, DWORD timeout_ms)
{
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(timeout_ms);
    while (std::chrono::steady_clock::now() < deadline) {
        if (GetClipboardSequenceNumber() != original_sequence ||
            IsClipboardFormatAvailable(CF_UNICODETEXT)) {
            return true;
        }
        Sleep(kClipboardPollIntervalMs);
    }
    return GetClipboardSequenceNumber() != original_sequence ||
           IsClipboardFormatAvailable(CF_UNICODETEXT);
}

std::unique_ptr<ClipboardSnapshot> SnapshotClipboard(HWND owner,
                                                     bool& complete,
                                                     std::string& diagnostic)
{
    auto snapshot = std::make_unique<ClipboardSnapshot>();
    if (!snapshot->Capture(owner)) {
        diagnostic =
            "The clipboard could not be snapshotted with the Win32 fallback";
        return nullptr;
    }
    complete = snapshot->complete();
    if (!complete) {
        diagnostic =
            "The Win32 clipboard snapshot omitted unsupported formats";
    }
    return snapshot;
}

template <typename CopyAction>
ClipboardCaptureAttempt CaptureClipboardChange(CopyAction copy,
                                               HWND clipboard_owner,
                                               DWORD timeout_ms,
                                               std::string& error)
{
    const auto started = std::chrono::steady_clock::now();
    ClipboardCaptureAttempt attempt;
    if (!EmptyClipboardSafely(clipboard_owner, error)) {
        attempt.duration_ms = ElapsedMs(started);
        return attempt;
    }
    attempt.clipboard_cleared = true;
    const DWORD sequence = GetClipboardSequenceNumber();
    attempt.action_sent = copy();
    if (attempt.action_sent) {
        attempt.clipboard_changed =
            WaitForClipboardText(sequence, timeout_ms);
    }
    if (attempt.clipboard_changed) {
        attempt.text = ReadClipboardText(clipboard_owner, error);
    }
    attempt.resulting_sequence = GetClipboardSequenceNumber();
    attempt.duration_ms = ElapsedMs(started);
    return attempt;
}
}  // namespace

SelectionCapture CaptureSelectedText(unsigned int active_modifiers,
                                     unsigned int active_virtual_key)
{
    const auto capture_started = std::chrono::steady_clock::now();
    std::ostringstream trace;
    auto finish_trace = [&](const char* result) {
        trace << " result=" << result
              << " total_ms=" << ElapsedMs(capture_started);
        return trace.str();
    };

    HWND foreground_window = GetForegroundWindow();
    HWND focused_window = GetFocusedWindow(foreground_window);
    std::string focused_class = WindowClassName(focused_window);
    const auto ui_started = std::chrono::steady_clock::now();
    UiSelection ui = TryGetUiSelection();
    bool focus_retried = false;
    if (foreground_window != GetForegroundWindow()) {
        focus_retried = true;
        foreground_window = GetForegroundWindow();
        focused_window = GetFocusedWindow(foreground_window);
        focused_class = WindowClassName(focused_window);
        ui = TryGetUiSelection();
    }
    trace << "uia_ms=" << ElapsedMs(ui_started)
          << " uia_text_length=" << ui.text.size()
          << " focus_retried=" << focus_retried
          << " focused_class=" << focused_class;
    if (!ui.text.empty()) {
        SelectionCapture result{ui.text, CaptureSource::UiAutomation, {}};
        result.trace = finish_trace("uia");
        return result;
    }

    const auto native_selection_started = std::chrono::steady_clock::now();
    const NativeSelectionState native_selection =
        GetNativeSelectionState(focused_window);
    trace << " target_higher_integrity="
          << TargetHasHigherIntegrity(focused_window)
          << " native_selection=" << NativeSelectionName(native_selection)
          << " native_selection_ms=" << ElapsedMs(native_selection_started);
    if (native_selection == NativeSelectionState::Empty) {
        SelectionCapture result;
        result.trace = finish_trace("native_empty");
        return result;
    }

    SelectionCapture result;
    auto capture_clipboard = [&] {
        try {
        ClipboardOwnerWindow owner_window;
        const HWND clipboard_owner = owner_window.get();

        const auto snapshot_started = std::chrono::steady_clock::now();
        winrt::com_ptr<IDataObject> ole_snapshot;
        const HRESULT ole_snapshot_result =
            OleGetClipboard(ole_snapshot.put());
        bool manual_snapshot_complete = false;
        std::string preservation_diagnostic;
        std::unique_ptr<ClipboardSnapshot> manual_snapshot;
        if (FAILED(ole_snapshot_result) || !ole_snapshot) {
            try {
                manual_snapshot = SnapshotClipboard(
                    clipboard_owner, manual_snapshot_complete,
                    preservation_diagnostic);
            } catch (const std::exception& error) {
                preservation_diagnostic = error.what();
            } catch (...) {
                preservation_diagnostic = "unknown_snapshot_exception";
            }
        }
        const char* snapshot_status = ole_snapshot
                                          ? "ole"
                                      : manual_snapshot == nullptr
                                          ? "failed"
                                      : manual_snapshot_complete
                                          ? "manual_complete"
                                          : "manual_partial";
        trace << " snapshot_ms=" << ElapsedMs(snapshot_started)
              << " snapshot_status=" << snapshot_status
              << " snapshot_warning=" << !preservation_diagnostic.empty()
              << " ole_snapshot_result="
              << static_cast<long>(ole_snapshot_result);

        // Prefer a command message because it does not disturb keyboard state.
        // Chromium host windows consistently ignore WM_COPY, so do not touch
        // the clipboard or spend a timeout probing them.
        const bool window_message_skipped =
            IsKnownUnsupportedWindowCopyClass(focused_class);
        bool window_message_delivered = false;
        DWORD_PTR window_message_result = 0;
        ClipboardCaptureAttempt window_message;
        DWORD captured_sequence = 0;
        if (!window_message_skipped) {
            window_message = CaptureClipboardChange(
                [&] {
                    return SendCopyMessage(focused_window,
                                           window_message_delivered,
                                           window_message_result);
                },
                clipboard_owner, kWindowMessageClipboardTimeoutMs,
                result.error);
        }
        trace << " wm_copy_ms=" << window_message.duration_ms
              << " wm_copy_skipped=" << window_message_skipped
              << " wm_copy_delivered=" << window_message_delivered
              << " wm_copy_result=" << window_message_result
              << " wm_copy_cleared=" << window_message.clipboard_cleared
              << " wm_copy_sent=" << window_message.action_sent
              << " wm_copy_changed=" << window_message.clipboard_changed
              << " wm_copy_text_length=" << window_message.text.size();
        result.text = window_message.text;
        if (!result.text.empty()) {
            result.source = CaptureSource::WindowMessage;
            captured_sequence = window_message.resulting_sequence;
        } else {
            // Electron and other custom controls may only implement keyboard
            // copy.
            const ClipboardCaptureAttempt synthetic = CaptureClipboardChange(
                [&] {
                    return SendCopyShortcut(active_modifiers,
                                            active_virtual_key, result.error);
                },
                clipboard_owner, kSyntheticClipboardTimeoutMs, result.error);
            trace << " synthetic_ms=" << synthetic.duration_ms
                  << " synthetic_cleared=" << synthetic.clipboard_cleared
                  << " synthetic_sent=" << synthetic.action_sent
                  << " synthetic_changed=" << synthetic.clipboard_changed
                  << " synthetic_text_length=" << synthetic.text.size();
            result.text = synthetic.text;
            if (!result.text.empty()) {
                result.source = CaptureSource::SyntheticShortcut;
            }
            captured_sequence = synthetic.resulting_sequence;
        }

        if (captured_sequence == 0) {
            captured_sequence = GetClipboardSequenceNumber();
        }
        const auto restore_started = std::chrono::steady_clock::now();
        const char* restore_status = "unavailable";
        HRESULT ole_restore_result = E_FAIL;
        const ClipboardRestoreDecision restore_decision = DecideClipboardRestore(
            ole_snapshot || manual_snapshot != nullptr, captured_sequence,
            GetClipboardSequenceNumber());
        if (restore_decision ==
            ClipboardRestoreDecision::SkipNewerContent) {
            restore_status = "skipped_newer_content";
        } else if (restore_decision == ClipboardRestoreDecision::Restore &&
                   ole_snapshot) {
            ole_restore_result = OleSetClipboard(ole_snapshot.get());
            restore_status = SUCCEEDED(ole_restore_result) ? "complete"
                                                           : "failed";
        } else if (restore_decision == ClipboardRestoreDecision::Restore &&
                   manual_snapshot != nullptr) {
            const bool restored = manual_snapshot->Restore(clipboard_owner);
            restore_status = !restored ? "failed"
                             : manual_snapshot_complete ? "complete"
                                                        : "partial";
        }
        trace << " restore_ms=" << ElapsedMs(restore_started)
              << " restore_status=" << restore_status
              << " ole_restore_result="
              << static_cast<long>(ole_restore_result);
        } catch (const std::exception& error) {
            result.error = error.what();
        } catch (...) {
            result.error = "Unknown clipboard capture failure";
        }
    };
    capture_clipboard();

    const char* capture_result = result.source == CaptureSource::WindowMessage
                                     ? "wm_copy"
                                 : result.source == CaptureSource::SyntheticShortcut
                                     ? "synthetic_copy"
                                     : "empty";
    result.trace = finish_trace(capture_result);
    return result;
}

void ShutdownSelectionCaptureForThread()
{
    g_automation = nullptr;
}

}  // namespace selectspeak::input
