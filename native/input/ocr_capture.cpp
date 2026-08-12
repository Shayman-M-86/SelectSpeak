#include <windows.h>
#include <windowsx.h>
#include <MemoryBuffer.h>
#include <shellscalingapi.h>

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Globalization.h>
#include <winrt/Windows.Graphics.Imaging.h>
#include <winrt/Windows.Media.Ocr.h>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#ifdef SELECTSPEAK_INPUT_EXPORTS
#define INPUT_API extern "C" __declspec(dllexport)
#else
#define INPUT_API extern "C" __declspec(dllimport)
#endif

using ocr_callback_t =
    void(__cdecl*)(const wchar_t*, unsigned int, void*);

namespace {
constexpr int kOcrHotkeyId = 2;
constexpr unsigned int kOcrCompleted = 1;
constexpr unsigned int kOcrCancelled = 2;
constexpr unsigned int kOcrFailed = 3;
constexpr wchar_t kOverlayClass[] = L"SelectSpeakOcrOverlay";
constexpr BYTE kOverlayShadeAlpha = 102;  // PowerToys uses 40% black.
constexpr COLORREF kSelectionBorderColor = RGB(40, 118, 126);
constexpr int kSelectionBorderDips = 2;
constexpr RECT kHintRect{20, 18, 520, 54};

struct Screenshot {
    HBITMAP bitmap = nullptr;
    void* pixels = nullptr;
    int x = 0;
    int y = 0;
    int width = 0;
    int height = 0;

    Screenshot() = default;
    Screenshot(const Screenshot&) = delete;
    Screenshot& operator=(const Screenshot&) = delete;
    Screenshot(Screenshot&& other) noexcept { *this = std::move(other); }
    Screenshot& operator=(Screenshot&& other) noexcept {
        if (this != &other) {
            if (bitmap != nullptr) {
                DeleteObject(bitmap);
            }
            bitmap = other.bitmap;
            pixels = other.pixels;
            x = other.x;
            y = other.y;
            width = other.width;
            height = other.height;
            other.bitmap = nullptr;
            other.pixels = nullptr;
        }
        return *this;
    }
    ~Screenshot() {
        if (bitmap != nullptr) {
            DeleteObject(bitmap);
        }
    }
};

struct Selection {
    POINT start{};
    POINT current{};
    bool dragging = false;
    bool selected = false;
};

struct OverlayContext {
    Screenshot* screenshot = nullptr;
    Selection selection;
    HDC screenshot_dc = nullptr;
    HDC frame_dc = nullptr;
    HDC shade_dc = nullptr;
    HBITMAP frame_bitmap = nullptr;
    HBITMAP shade_bitmap = nullptr;
    HGDIOBJ old_screenshot = nullptr;
    HGDIOBJ old_frame = nullptr;
    HGDIOBJ old_shade = nullptr;
    int border_width = kSelectionBorderDips;

    ~OverlayContext() {
        if (screenshot_dc != nullptr) {
            SelectObject(screenshot_dc, old_screenshot);
        }
        if (frame_dc != nullptr) {
            SelectObject(frame_dc, old_frame);
        }
        if (shade_dc != nullptr) {
            SelectObject(shade_dc, old_shade);
        }
        if (frame_bitmap != nullptr) {
            DeleteObject(frame_bitmap);
        }
        if (shade_bitmap != nullptr) {
            DeleteObject(shade_bitmap);
        }
        if (screenshot_dc != nullptr) {
            DeleteDC(screenshot_dc);
        }
        if (frame_dc != nullptr) {
            DeleteDC(frame_dc);
        }
        if (shade_dc != nullptr) {
            DeleteDC(shade_dc);
        }
    }
};

struct OcrState {
    std::mutex lifecycle_mutex;
    std::thread thread;
    std::atomic<bool> running{false};
    std::atomic<bool> stopping{false};
    std::atomic<bool> active{false};
    std::atomic<HWND> overlay{nullptr};
    DWORD thread_id = 0;
    unsigned int modifiers = 0;
    unsigned int virtual_key = 0;
    std::wstring language;
    ocr_callback_t callback = nullptr;
    void* callback_context = nullptr;

    std::mutex ready_mutex;
    std::condition_variable ready_changed;
    bool ready = false;
    bool start_succeeded = false;

    std::mutex error_mutex;
    std::string last_error;
};

OcrState g_ocr;

void SetOcrError(const std::string& message) {
    std::lock_guard lock(g_ocr.error_mutex);
    g_ocr.last_error = message;
}

void SetOcrWindowsError(const char* operation) {
    SetOcrError(std::string(operation) + " failed with Windows error " +
                std::to_string(GetLastError()));
}

RECT NormalizedSelection(const OverlayContext& context) {
    return {
        std::min(context.selection.start.x, context.selection.current.x),
        std::min(context.selection.start.y, context.selection.current.y),
        std::max(context.selection.start.x, context.selection.current.x),
        std::max(context.selection.start.y, context.selection.current.y),
    };
}

POINT ClampedPoint(HWND window, LPARAM value) {
    RECT client{};
    GetClientRect(window, &client);
    return {
        std::clamp<LONG>(GET_X_LPARAM(value), client.left, client.right),
        std::clamp<LONG>(GET_Y_LPARAM(value), client.top, client.bottom),
    };
}

UINT SelectionDpi(HWND window, const OverlayContext& context,
                  const POINT& client_point) {
    POINT screen_point{
        context.screenshot->x + client_point.x,
        context.screenshot->y + client_point.y,
    };
    HMONITOR monitor = MonitorFromPoint(screen_point, MONITOR_DEFAULTTONEAREST);
    UINT horizontal = 0;
    UINT vertical = 0;
    if (monitor != nullptr &&
        SUCCEEDED(GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &horizontal,
                                   &vertical)) &&
        horizontal > 0) {
        return horizontal;
    }
    return GetDpiForWindow(window);
}

RECT ClampRect(const OverlayContext& context, RECT area) {
    area.left = std::clamp<LONG>(area.left, 0, context.screenshot->width);
    area.top = std::clamp<LONG>(area.top, 0, context.screenshot->height);
    area.right = std::clamp<LONG>(area.right, 0, context.screenshot->width);
    area.bottom = std::clamp<LONG>(area.bottom, 0, context.screenshot->height);
    return area;
}

RECT ExpandedSelection(const OverlayContext& context, const RECT& selected) {
    const int padding = context.border_width + 2;
    return ClampRect(context, {
        selected.left - padding,
        selected.top - padding,
        selected.right + padding,
        selected.bottom + padding,
    });
}

bool HasArea(const RECT& area) {
    return area.right > area.left && area.bottom > area.top;
}

void RestoreDimmedRegion(OverlayContext& context, const RECT& requested) {
    const RECT area = ClampRect(context, requested);
    if (!HasArea(area)) {
        return;
    }
    const int width = area.right - area.left;
    const int height = area.bottom - area.top;
    BitBlt(context.frame_dc, area.left, area.top, width, height,
           context.screenshot_dc, area.left, area.top, SRCCOPY);
    BLENDFUNCTION blend{AC_SRC_OVER, 0, kOverlayShadeAlpha, 0};
    AlphaBlend(context.frame_dc, area.left, area.top, width, height,
               context.shade_dc, 0, 0, 1, 1, blend);
}

void DrawSelection(OverlayContext& context, const RECT& selected) {
    const int width = selected.right - selected.left;
    const int height = selected.bottom - selected.top;
    if (width <= 0 || height <= 0) {
        return;
    }
    BitBlt(context.frame_dc, selected.left, selected.top, width, height,
           context.screenshot_dc, selected.left, selected.top, SRCCOPY);

    const int half_border = std::max(1, context.border_width / 2);
    HPEN pen = CreatePen(PS_SOLID, context.border_width,
                         kSelectionBorderColor);
    HGDIOBJ old_pen = SelectObject(context.frame_dc, pen);
    HGDIOBJ old_brush = SelectObject(
        context.frame_dc, GetStockObject(HOLLOW_BRUSH));
    Rectangle(context.frame_dc, selected.left - half_border,
              selected.top - half_border, selected.right + half_border,
              selected.bottom + half_border);
    SelectObject(context.frame_dc, old_brush);
    SelectObject(context.frame_dc, old_pen);
    DeleteObject(pen);
}

void DrawHint(OverlayContext& context) {
    SetBkMode(context.frame_dc, TRANSPARENT);
    SetTextColor(context.frame_dc, RGB(255, 255, 255));
    RECT hint = kHintRect;
    DrawTextW(context.frame_dc, L"Drag around text  |  Esc to cancel", -1,
              &hint, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
}

bool InitializeOverlayFrame(OverlayContext& context) {
    HDC screen = GetDC(nullptr);
    context.screenshot_dc = CreateCompatibleDC(screen);
    context.frame_dc = CreateCompatibleDC(screen);
    context.shade_dc = CreateCompatibleDC(screen);
    context.frame_bitmap = CreateCompatibleBitmap(
        screen, context.screenshot->width, context.screenshot->height);
    context.shade_bitmap = CreateCompatibleBitmap(screen, 1, 1);
    ReleaseDC(nullptr, screen);
    if (context.screenshot_dc == nullptr || context.frame_dc == nullptr ||
        context.shade_dc == nullptr || context.frame_bitmap == nullptr ||
        context.shade_bitmap == nullptr) {
        return false;
    }

    context.old_screenshot = SelectObject(
        context.screenshot_dc, context.screenshot->bitmap);
    context.old_frame = SelectObject(context.frame_dc, context.frame_bitmap);
    context.old_shade = SelectObject(context.shade_dc, context.shade_bitmap);
    SetPixel(context.shade_dc, 0, 0, RGB(0, 0, 0));
    RestoreDimmedRegion(context, {
        0,
        0,
        context.screenshot->width,
        context.screenshot->height,
    });
    DrawHint(context);
    return true;
}

void UpdateSelectionFrame(HWND window, OverlayContext& context,
                          const RECT& previous) {
    const RECT current = NormalizedSelection(context);
    const RECT previous_dirty = ExpandedSelection(context, previous);
    const RECT current_dirty = ExpandedSelection(context, current);
    RestoreDimmedRegion(context, previous_dirty);
    DrawSelection(context, current);
    RECT dirty{};
    UnionRect(&dirty, &previous_dirty, &current_dirty);
    InvalidateRect(window, &dirty, FALSE);
}

void PaintOverlay(HWND window, OverlayContext& context) {
    PAINTSTRUCT paint{};
    HDC destination = BeginPaint(window, &paint);
    if (HasArea(paint.rcPaint)) {
        BitBlt(destination, paint.rcPaint.left, paint.rcPaint.top,
               paint.rcPaint.right - paint.rcPaint.left,
               paint.rcPaint.bottom - paint.rcPaint.top, context.frame_dc,
               paint.rcPaint.left, paint.rcPaint.top, SRCCOPY);
    }
    EndPaint(window, &paint);
}

LRESULT CALLBACK OverlayProcedure(HWND window, UINT message, WPARAM wparam,
                                  LPARAM lparam) {
    auto* context = reinterpret_cast<OverlayContext*>(
        GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
        auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
        context = static_cast<OverlayContext*>(create->lpCreateParams);
        SetWindowLongPtrW(window, GWLP_USERDATA,
                          reinterpret_cast<LONG_PTR>(context));
    }
    if (context == nullptr) {
        return DefWindowProcW(window, message, wparam, lparam);
    }

    switch (message) {
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT:
        PaintOverlay(window, *context);
        return 0;
    case WM_SETCURSOR:
        SetCursor(LoadCursorW(nullptr, IDC_CROSS));
        return TRUE;
    case WM_LBUTTONDOWN:
        context->selection.start = ClampedPoint(window, lparam);
        context->border_width = std::max(
            kSelectionBorderDips,
            MulDiv(kSelectionBorderDips,
                   SelectionDpi(window, *context, context->selection.start),
                   96));
        RestoreDimmedRegion(*context, kHintRect);
        context->selection.current = context->selection.start;
        context->selection.dragging = true;
        SetCapture(window);
        InvalidateRect(window, &kHintRect, FALSE);
        return 0;
    case WM_MOUSEMOVE:
        if (context->selection.dragging) {
            const RECT previous = NormalizedSelection(*context);
            context->selection.current = ClampedPoint(window, lparam);
            UpdateSelectionFrame(window, *context, previous);
        }
        return 0;
    case WM_LBUTTONUP:
        if (context->selection.dragging) {
            context->selection.current = ClampedPoint(window, lparam);
            context->selection.dragging = false;
            ReleaseCapture();
            const RECT selected = NormalizedSelection(*context);
            context->selection.selected =
                selected.right - selected.left >= 3 &&
                selected.bottom - selected.top >= 3;
            DestroyWindow(window);
        }
        return 0;
    case WM_KEYDOWN:
        if (wparam != VK_ESCAPE) {
            return 0;
        }
        [[fallthrough]];
    case WM_RBUTTONDOWN:
    case WM_CLOSE:
        context->selection.dragging = false;
        context->selection.selected = false;
        if (GetCapture() == window) {
            ReleaseCapture();
        }
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        g_ocr.overlay.store(nullptr);
        return 0;
    default:
        return DefWindowProcW(window, message, wparam, lparam);
    }
}

Screenshot CaptureVirtualScreen() {
    Screenshot screenshot;
    screenshot.x = GetSystemMetrics(SM_XVIRTUALSCREEN);
    screenshot.y = GetSystemMetrics(SM_YVIRTUALSCREEN);
    screenshot.width = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    screenshot.height = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    if (screenshot.width <= 0 || screenshot.height <= 0) {
        throw std::runtime_error("Windows reported an empty virtual screen");
    }

    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = screenshot.width;
    info.bmiHeader.biHeight = -screenshot.height;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;

    HDC screen = GetDC(nullptr);
    HDC memory = CreateCompatibleDC(screen);
    screenshot.bitmap = CreateDIBSection(
        screen, &info, DIB_RGB_COLORS, &screenshot.pixels, nullptr, 0);
    if (screen == nullptr || memory == nullptr || screenshot.bitmap == nullptr) {
        if (memory != nullptr) {
            DeleteDC(memory);
        }
        if (screen != nullptr) {
            ReleaseDC(nullptr, screen);
        }
        throw std::runtime_error("Could not allocate the frozen screen bitmap");
    }
    HGDIOBJ old = SelectObject(memory, screenshot.bitmap);
    const BOOL copied = BitBlt(memory, 0, 0, screenshot.width,
                               screenshot.height, screen, screenshot.x,
                               screenshot.y, SRCCOPY | CAPTUREBLT);
    SelectObject(memory, old);
    DeleteDC(memory);
    ReleaseDC(nullptr, screen);
    if (!copied) {
        throw std::runtime_error("Could not capture the Windows desktop");
    }
    return screenshot;
}

bool SelectScreenRegion(Screenshot& screenshot, RECT& selected) {
    OverlayContext context{&screenshot};
    if (!InitializeOverlayFrame(context)) {
        throw std::runtime_error("Could not allocate the OCR overlay frame");
    }
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = OverlayProcedure;
    window_class.hInstance = instance;
    window_class.hCursor = LoadCursorW(nullptr, IDC_CROSS);
    window_class.lpszClassName = kOverlayClass;
    RegisterClassW(&window_class);

    HWND window = CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW, kOverlayClass, L"SelectSpeak OCR",
        WS_POPUP, screenshot.x, screenshot.y, screenshot.width,
        screenshot.height, nullptr, nullptr, instance, &context);
    if (window == nullptr) {
        SetOcrWindowsError("CreateWindowExW");
        throw std::runtime_error("Could not create the OCR selection overlay");
    }
    g_ocr.overlay.store(window);
    SetWindowPos(window, HWND_TOPMOST, screenshot.x, screenshot.y,
                 screenshot.width, screenshot.height, SWP_SHOWWINDOW);
    SetForegroundWindow(window);
    SetFocus(window);
    UpdateWindow(window);

    MSG message{};
    while (IsWindow(window)) {
        const BOOL result = GetMessageW(&message, nullptr, 0, 0);
        if (result <= 0) {
            if (IsWindow(window)) {
                DestroyWindow(window);
            }
            break;
        }
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    if (!context.selection.selected) {
        return false;
    }
    selected = NormalizedSelection(context);
    return true;
}

winrt::Windows::Graphics::Imaging::SoftwareBitmap CopyBgraBitmap(
    const std::uint8_t* pixels, int width, int height, int source_stride);

winrt::Windows::Graphics::Imaging::SoftwareBitmap CreateOcrBitmap(
    const Screenshot& screenshot, const RECT& selected,
    unsigned int maximum_dimension) {
    const int source_width = selected.right - selected.left;
    const int source_height = selected.bottom - selected.top;
    const double scale = std::min(
        {1.0, static_cast<double>(maximum_dimension) / source_width,
         static_cast<double>(maximum_dimension) / source_height});
    const int width = std::max(1, static_cast<int>(source_width * scale));
    const int height = std::max(1, static_cast<int>(source_height * scale));

    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = width;
    info.bmiHeader.biHeight = -height;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;
    void* scaled_pixels = nullptr;
    HDC screen = GetDC(nullptr);
    HBITMAP scaled = CreateDIBSection(
        screen, &info, DIB_RGB_COLORS, &scaled_pixels, nullptr, 0);
    HDC source = CreateCompatibleDC(screen);
    HDC destination = CreateCompatibleDC(screen);
    if (scaled == nullptr || source == nullptr || destination == nullptr) {
        if (scaled != nullptr) {
            DeleteObject(scaled);
        }
        if (source != nullptr) {
            DeleteDC(source);
        }
        if (destination != nullptr) {
            DeleteDC(destination);
        }
        ReleaseDC(nullptr, screen);
        throw std::runtime_error("Could not allocate the selected OCR bitmap");
    }
    HGDIOBJ old_source = SelectObject(source, screenshot.bitmap);
    HGDIOBJ old_destination = SelectObject(destination, scaled);
    SetStretchBltMode(destination, HALFTONE);
    SetBrushOrgEx(destination, 0, 0, nullptr);
    const BOOL copied = StretchBlt(
        destination, 0, 0, width, height, source, selected.left, selected.top,
        source_width, source_height, SRCCOPY);
    SelectObject(destination, old_destination);
    SelectObject(source, old_source);
    DeleteDC(destination);
    DeleteDC(source);
    ReleaseDC(nullptr, screen);
    if (!copied) {
        DeleteObject(scaled);
        throw std::runtime_error("Could not prepare the selected OCR pixels");
    }

    auto bitmap = CopyBgraBitmap(
        static_cast<const std::uint8_t*>(scaled_pixels), width, height,
        width * 4);
    DeleteObject(scaled);
    return bitmap;
}

winrt::Windows::Graphics::Imaging::SoftwareBitmap CopyBgraBitmap(
    const std::uint8_t* pixels, int width, int height, int source_stride) {
    using namespace winrt::Windows::Graphics::Imaging;
    SoftwareBitmap bitmap(BitmapPixelFormat::Bgra8, width, height,
                          BitmapAlphaMode::Ignore);
    auto buffer = bitmap.LockBuffer(BitmapBufferAccessMode::Write);
    auto reference = buffer.CreateReference();
    std::uint8_t* destination = nullptr;
    std::uint32_t capacity = 0;
    winrt::check_hresult(
        reference.as<::Windows::Foundation::IMemoryBufferByteAccess>()
            ->GetBuffer(&destination, &capacity));
    const auto plane = buffer.GetPlaneDescription(0);
    const int row_bytes = width * 4;
    for (int row = 0; row < height; ++row) {
        std::memcpy(destination + plane.StartIndex + row * plane.Stride,
                    pixels + row * source_stride, row_bytes);
    }
    return bitmap;
}

std::wstring ForegroundLanguage() {
    DWORD thread = GetWindowThreadProcessId(GetForegroundWindow(), nullptr);
    HKL layout = GetKeyboardLayout(thread);
    const LANGID language_id = LOWORD(reinterpret_cast<ULONG_PTR>(layout));
    wchar_t locale[LOCALE_NAME_MAX_LENGTH]{};
    if (LCIDToLocaleName(MAKELCID(language_id, SORT_DEFAULT), locale,
                         LOCALE_NAME_MAX_LENGTH, 0)) {
        return locale;
    }
    return {};
}

winrt::Windows::Media::Ocr::OcrEngine CreateOcrEngine(
    const std::wstring& configured_language,
    const std::wstring& foreground_language) {
    using winrt::Windows::Globalization::Language;
    using winrt::Windows::Media::Ocr::OcrEngine;

    auto try_language = [](const std::wstring& tag) -> OcrEngine {
        if (tag.empty()) {
            return nullptr;
        }
        try {
            Language language(tag);
            if (OcrEngine::IsLanguageSupported(language)) {
                return OcrEngine::TryCreateFromLanguage(language);
            }
        } catch (const winrt::hresult_error&) {
        }
        return nullptr;
    };

    OcrEngine engine = try_language(configured_language);
    if (!engine) {
        engine = try_language(foreground_language);
    }
    if (!engine) {
        engine = try_language(L"en-US");
    }
    if (!engine) {
        engine = OcrEngine::TryCreateFromUserProfileLanguages();
    }
    if (!engine) {
        throw std::runtime_error(
            "Windows has no OCR language available for this selection");
    }
    return engine;
}

std::wstring RecognizeBitmap(
    const winrt::Windows::Graphics::Imaging::SoftwareBitmap& bitmap,
    const std::wstring& configured_language,
    const std::wstring& foreground_language) {
    auto engine = CreateOcrEngine(configured_language, foreground_language);
    return std::wstring(engine.RecognizeAsync(bitmap).get().Text());
}

void SendResult(const std::wstring& text, unsigned int status) {
    if (g_ocr.callback != nullptr) {
        g_ocr.callback(text.empty() ? nullptr : text.c_str(), status,
                       g_ocr.callback_context);
    }
}

void CaptureAndRecognize() {
    const std::wstring foreground_language = ForegroundLanguage();
    Screenshot screenshot = CaptureVirtualScreen();
    RECT selected{};
    if (!SelectScreenRegion(screenshot, selected)) {
        if (!g_ocr.stopping.load()) {
            SendResult({}, kOcrCancelled);
        }
        return;
    }
    if (g_ocr.stopping.load()) {
        return;
    }

    using winrt::Windows::Media::Ocr::OcrEngine;
    auto bitmap = CreateOcrBitmap(screenshot, selected,
                                  OcrEngine::MaxImageDimension());
    SendResult(RecognizeBitmap(bitmap, g_ocr.language, foreground_language),
               kOcrCompleted);
}

void SignalReady(bool succeeded) {
    {
        std::lock_guard lock(g_ocr.ready_mutex);
        g_ocr.start_succeeded = succeeded;
        g_ocr.ready = true;
    }
    g_ocr.ready_changed.notify_one();
}

void OcrThread() {
    bool ready_signalled = false;
    bool apartment_initialized = false;
    bool hotkey_registered = false;
    try {
        winrt::init_apartment(winrt::apartment_type::multi_threaded);
        apartment_initialized = true;
        g_ocr.thread_id = GetCurrentThreadId();
        if (!RegisterHotKey(nullptr, kOcrHotkeyId,
                            g_ocr.modifiers | MOD_NOREPEAT,
                            g_ocr.virtual_key)) {
            SetOcrWindowsError("RegisterHotKey");
            SignalReady(false);
            ready_signalled = true;
        } else {
            hotkey_registered = true;
            SignalReady(true);
            ready_signalled = true;

            MSG message{};
            while (!g_ocr.stopping.load() &&
                   GetMessageW(&message, nullptr, 0, 0) > 0) {
                if (message.message != WM_HOTKEY ||
                    message.wParam != kOcrHotkeyId ||
                    g_ocr.active.exchange(true)) {
                    TranslateMessage(&message);
                    DispatchMessageW(&message);
                    continue;
                }
                try {
                    CaptureAndRecognize();
                } catch (const winrt::hresult_error& error) {
                    SetOcrError(winrt::to_string(error.message()));
                    SendResult({}, kOcrFailed);
                } catch (const std::exception& error) {
                    SetOcrError(error.what());
                    SendResult({}, kOcrFailed);
                }
                g_ocr.active.store(false);
            }
        }
    } catch (const winrt::hresult_error& error) {
        SetOcrError(winrt::to_string(error.message()));
        if (!ready_signalled) {
            SignalReady(false);
        }
    } catch (const std::exception& error) {
        SetOcrError(error.what());
        if (!ready_signalled) {
            SignalReady(false);
        }
    }
    if (hotkey_registered) {
        UnregisterHotKey(nullptr, kOcrHotkeyId);
    }
    if (apartment_initialized) {
        winrt::uninit_apartment();
    }
    g_ocr.thread_id = 0;
    g_ocr.active.store(false);
    g_ocr.running.store(false);
}
}  // namespace

INPUT_API int ocr_start(unsigned int modifiers, unsigned int virtual_key,
                        const wchar_t* language, ocr_callback_t callback,
                        void* context) {
    std::lock_guard lifecycle_lock(g_ocr.lifecycle_mutex);
    if (g_ocr.running.load()) {
        SetOcrError("The native OCR adapter is already running");
        return 1;
    }
    if (callback == nullptr || virtual_key == 0) {
        SetOcrError("An OCR callback and virtual key are required");
        return 1;
    }
    if (g_ocr.thread.joinable()) {
        g_ocr.thread.join();
    }
    g_ocr.modifiers = modifiers;
    g_ocr.virtual_key = virtual_key;
    g_ocr.language = language == nullptr ? L"" : language;
    g_ocr.callback = callback;
    g_ocr.callback_context = context;
    g_ocr.stopping.store(false);
    g_ocr.active.store(false);
    g_ocr.ready = false;
    g_ocr.start_succeeded = false;
    g_ocr.running.store(true);
    g_ocr.thread = std::thread(OcrThread);
    {
        std::unique_lock ready_lock(g_ocr.ready_mutex);
        g_ocr.ready_changed.wait(ready_lock, [] { return g_ocr.ready; });
    }
    if (!g_ocr.start_succeeded) {
        if (g_ocr.thread.joinable()) {
            g_ocr.thread.join();
        }
        g_ocr.running.store(false);
        return 1;
    }
    return 0;
}

INPUT_API void ocr_cancel() {
    HWND overlay = g_ocr.overlay.load();
    if (overlay != nullptr) {
        PostMessageW(overlay, WM_CLOSE, 0, 0);
    }
}

INPUT_API int ocr_is_active() { return g_ocr.active.load() ? 1 : 0; }

INPUT_API void ocr_stop() {
    std::lock_guard lifecycle_lock(g_ocr.lifecycle_mutex);
    if (!g_ocr.running.load() && !g_ocr.thread.joinable()) {
        return;
    }
    g_ocr.stopping.store(true);
    ocr_cancel();
    if (g_ocr.thread_id != 0) {
        PostThreadMessageW(g_ocr.thread_id, WM_QUIT, 0, 0);
    }
    if (g_ocr.thread.joinable()) {
        g_ocr.thread.join();
    }
    g_ocr.callback = nullptr;
    g_ocr.callback_context = nullptr;
    g_ocr.running.store(false);
}

INPUT_API unsigned int ocr_last_error(char* buffer, unsigned int length) {
    std::lock_guard lock(g_ocr.error_mutex);
    const unsigned int required =
        static_cast<unsigned int>(g_ocr.last_error.size() + 1);
    if (buffer != nullptr && length > 0) {
        const unsigned int count = std::min(required, length);
        std::memcpy(buffer, g_ocr.last_error.c_str(), count - 1);
        buffer[count - 1] = '\0';
    }
    return required;
}

INPUT_API int ocr_recognize_bgra(const unsigned char* pixels,
                                 unsigned int width, unsigned int height,
                                 unsigned int stride, const wchar_t* language,
                                 ocr_callback_t callback, void* context) {
    if (pixels == nullptr || width == 0 || height == 0 || stride < width * 4 ||
        callback == nullptr) {
        SetOcrError("Valid BGRA pixels, dimensions, stride, and callback are required");
        return 1;
    }
    std::wstring recognized;
    std::string failure;
    const std::wstring language_tag = language == nullptr ? L"" : language;
    std::thread worker([&] {
        bool apartment_initialized = false;
        try {
            winrt::init_apartment(winrt::apartment_type::multi_threaded);
            apartment_initialized = true;
            auto bitmap = CopyBgraBitmap(pixels, static_cast<int>(width),
                                         static_cast<int>(height),
                                         static_cast<int>(stride));
            recognized = RecognizeBitmap(bitmap, language_tag, L"");
        } catch (const winrt::hresult_error& error) {
            failure = winrt::to_string(error.message());
        } catch (const std::exception& error) {
            failure = error.what();
        }
        if (apartment_initialized) {
            winrt::uninit_apartment();
        }
    });
    worker.join();
    if (!failure.empty()) {
        SetOcrError(failure);
        callback(nullptr, kOcrFailed, context);
        return 1;
    }
    callback(recognized.empty() ? nullptr : recognized.c_str(), kOcrCompleted,
             context);
    return 0;
}
