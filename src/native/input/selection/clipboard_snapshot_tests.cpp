// Round-trip coverage for the clipboard preservation mechanism.
//
// This exercises the real Win32 behaviour the capture path depends on: the
// data must be duplicated eagerly, because EmptyClipboard destroys whatever
// the owning application published. A proxy obtained from OleGetClipboard
// does not survive that, which is why the capture path duplicates instead.
//
// The snapshot implementation lives in an anonymous namespace inside
// selection_capture.cpp, so this test reproduces the same sequence directly
// against the clipboard rather than linking to it.

#include <windows.h>
#include <ole2.h>

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

void Expect(bool condition, const char* message)
{
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
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

HGLOBAL AllocateText(const std::wstring& text)
{
    const SIZE_T bytes = (text.size() + 1) * sizeof(wchar_t);
    HGLOBAL handle = GlobalAlloc(GMEM_MOVEABLE, bytes);
    if (handle == nullptr) {
        return nullptr;
    }
    auto* target = static_cast<wchar_t*>(GlobalLock(handle));
    if (target == nullptr) {
        GlobalFree(handle);
        return nullptr;
    }
    std::memcpy(target, text.c_str(), bytes);
    GlobalUnlock(handle);
    return handle;
}

bool PublishText(HWND owner, const std::wstring& text)
{
    ClipboardScope clipboard(owner);
    if (!clipboard || !EmptyClipboard()) {
        return false;
    }
    HGLOBAL handle = AllocateText(text);
    if (handle == nullptr) {
        return false;
    }
    if (SetClipboardData(CF_UNICODETEXT, handle) == nullptr) {
        GlobalFree(handle);
        return false;
    }
    return true;
}

std::wstring ReadText(HWND owner)
{
    ClipboardScope clipboard(owner);
    if (!clipboard) {
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

// The eager duplicate the capture path performs before it empties the
// clipboard, mirroring ClipboardSnapshot::Capture / ::Restore.
struct Snapshot {
    UINT format = 0;
    HANDLE data = nullptr;
};

Snapshot Duplicate(HWND owner)
{
    ClipboardScope clipboard(owner);
    Snapshot snapshot;
    if (!clipboard) {
        return snapshot;
    }
    HANDLE source = GetClipboardData(CF_UNICODETEXT);
    if (source == nullptr) {
        return snapshot;
    }
    snapshot.format = CF_UNICODETEXT;
    snapshot.data = OleDuplicateData(source, CF_UNICODETEXT, GMEM_MOVEABLE);
    return snapshot;
}

bool Restore(HWND owner, Snapshot& snapshot)
{
    ClipboardScope clipboard(owner);
    if (!clipboard || snapshot.data == nullptr || !EmptyClipboard()) {
        return false;
    }
    if (SetClipboardData(snapshot.format, snapshot.data) == nullptr) {
        return false;
    }
    snapshot.data = nullptr;  // The clipboard owns it now.
    return true;
}

bool EmptyClipboardNow(HWND owner)
{
    ClipboardScope clipboard(owner);
    return clipboard && EmptyClipboard();
}

}  // namespace

int main()
{
    HWND owner = CreateWindowExW(0, L"STATIC", L"", 0, 0, 0, 0, 0, HWND_MESSAGE,
                                 nullptr, GetModuleHandleW(nullptr), nullptr);
    Expect(owner != nullptr, "A message-only clipboard owner is required");

    const std::wstring original = L"SelectSpeak clipboard round trip";
    Expect(PublishText(owner, original), "The test clipboard text should publish");
    Expect(ReadText(owner) == original, "The published text should read back");

    // Duplicate first, exactly as the capture path does.
    Snapshot snapshot = Duplicate(owner);
    Expect(snapshot.data != nullptr, "Clipboard data should duplicate eagerly");

    // The destructive probe: this is what a failed selection capture does.
    Expect(EmptyClipboardNow(owner), "The clipboard should empty for the probe");
    Expect(ReadText(owner).empty(), "The probe should leave the clipboard empty");

    // An eager duplicate survives the probe; an OLE proxy would not.
    Expect(Restore(owner, snapshot), "The duplicated data should restore");
    Expect(ReadText(owner) == original,
           "Restoring must return the original clipboard text");

    DestroyWindow(owner);
    return 0;
}
