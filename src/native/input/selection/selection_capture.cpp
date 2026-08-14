#include "selection_capture.h"

#include <windows.h>
#include <ole2.h>
#include <uiautomation.h>

#include <chrono>
#include <memory>
#include <string>
#include <vector>

namespace selectspeak::input {
namespace {
constexpr DWORD kClipboardTimeoutMs = 1000;

std::string WindowsError(const char* action, DWORD code = GetLastError())
{
    return std::string(action) + " failed with Windows error " +
           std::to_string(code);
}

bool OpenClipboardWithRetry()
{
    for (int attempt = 0; attempt < 10; ++attempt) {
        if (OpenClipboard(nullptr)) {
            return true;
        }
        Sleep(10);
    }
    return false;
}

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
    return OleDuplicateData(source, format, GMEM_MOVEABLE);
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
    bool Capture()
    {
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
            HANDLE duplicate = source == nullptr
                                   ? nullptr
                                   : DuplicateClipboardData(format, source);
            if (duplicate != nullptr) {
                entries_.emplace_back(format, duplicate);
            } else {
                captured_all = false;
            }
        }
        CloseClipboard();
        return captured_all;
    }

    bool Restore()
    {
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
                entry.data = nullptr;
            }
        }
        CloseClipboard();
        return restored_all;
    }

private:
    std::vector<ClipboardEntry> entries_;
};

struct UiSelection {
    std::wstring text;
    bool supported = false;
};

std::wstring GetTextPatternSelection(IUIAutomationElement* element,
                                     bool& pattern_supported)
{
    IUnknown* unknown = nullptr;
    if (FAILED(element->GetCurrentPattern(UIA_TextPatternId, &unknown)) ||
        unknown == nullptr) {
        return {};
    }
    IUIAutomationTextPattern* pattern = nullptr;
    const HRESULT query_result = unknown->QueryInterface(IID_PPV_ARGS(&pattern));
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
    pattern_supported = true;

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

UiSelection TryGetUiSelection()
{
    IUIAutomation* automation = nullptr;
    if (FAILED(CoCreateInstance(CLSID_CUIAutomation, nullptr,
                                CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&automation))) ||
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
    UiSelection result;
    for (int depth = 0; depth < 8 && element != nullptr; ++depth) {
        bool pattern_supported = false;
        result.text = GetTextPatternSelection(element, pattern_supported);
        result.supported = result.supported || pattern_supported;
        if (!result.text.empty() || walker == nullptr) {
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
    return result;
}

bool EmptyClipboardSafely(std::string& error)
{
    if (!OpenClipboardWithRetry()) {
        error = WindowsError("OpenClipboard");
        return false;
    }
    const BOOL emptied = EmptyClipboard();
    const DWORD code = emptied ? ERROR_SUCCESS : GetLastError();
    CloseClipboard();
    if (!emptied) {
        error = WindowsError("EmptyClipboard", code);
        return false;
    }
    return true;
}

std::wstring ReadClipboardText(std::string& error)
{
    if (!OpenClipboardWithRetry()) {
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
    CloseClipboard();
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

bool SendCopyShortcut(unsigned int modifiers, std::string& error)
{
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
        error = WindowsError("SendInput");
        return false;
    }
    return true;
}

bool WaitForClipboardChange(DWORD original_sequence)
{
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

std::unique_ptr<ClipboardSnapshot> SnapshotClipboard(std::string& error)
{
    auto snapshot = std::make_unique<ClipboardSnapshot>();
    if (!snapshot->Capture()) {
        error = "The clipboard could not be snapshotted without losing formats";
        return nullptr;
    }
    return snapshot;
}
}  // namespace

SelectionCapture CaptureSelectedText(unsigned int active_modifiers)
{
    const UiSelection ui = TryGetUiSelection();
    if (!ui.text.empty()) {
        return {ui.text, CaptureSource::UiAutomation, {}};
    }
    if (ui.supported) {
        return {};
    }

    SelectionCapture result;
    auto saved = SnapshotClipboard(result.error);
    if (saved == nullptr) {
        return result;
    }

    if (EmptyClipboardSafely(result.error)) {
        const DWORD sequence = GetClipboardSequenceNumber();
        if (SendCopyShortcut(active_modifiers, result.error) &&
            WaitForClipboardChange(sequence)) {
            result.text = ReadClipboardText(result.error);
            if (!result.text.empty()) {
                result.source = CaptureSource::Clipboard;
            }
        }
    }

    if (!saved->Restore()) {
        result.error =
            "The native input adapter could not restore the previous clipboard";
    }
    return result;
}

}  // namespace selectspeak::input
