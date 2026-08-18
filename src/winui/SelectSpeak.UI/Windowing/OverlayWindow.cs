using System;
using Microsoft.UI.Xaml;

namespace SelectSpeak.UI.Windowing;

/// <summary>
/// The Win32 the presenter API does not cover: keeping the window from stealing
/// focus, DWM chrome, and a global hotkey. Reached through
/// WindowNative.GetWindowHandle instead of winfo_id().
/// </summary>
public sealed class OverlayWindow : IDisposable
{
    private readonly IntPtr _hwnd;

    // The subclass must be kept alive for as long as it is installed, or the
    // delegate is collected and Windows calls into freed memory.
    private Interop.WindowProcedure? _subclass;
    private IntPtr _previousProcedure;
    private readonly System.Collections.Generic.Dictionary<int, Action> _hotkeys = new();
    private int _nextHotkeyId = 1;

    public OverlayWindow(Window window)
    {
        _hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
    }

    public IntPtr Handle => _hwnd;

    /// <summary>
    /// Clicking the window must not steal foreground from the app being read.
    /// </summary>
    public void EnableNoActivate()
    {
        var style = (int)Interop.GetWindowLongPtrW(_hwnd, Interop.GWL_EXSTYLE);

        // SetWindowLongPtr returns 0 both when the previous value was 0 and on
        // failure, so the last error is cleared first to tell them apart.
        Interop.SetLastError(0);
        var previous = Interop.SetWindowLongPtrW(
            _hwnd, Interop.GWL_EXSTYLE, new IntPtr(style | Interop.WS_EX_NOACTIVATE));
        if (previous == IntPtr.Zero)
        {
            var error = System.Runtime.InteropServices.Marshal.GetLastWin32Error();
            if (error != 0)
            {
                throw new System.ComponentModel.Win32Exception(
                    error, "SetWindowLongPtr(GWL_EXSTYLE) failed");
            }
        }

        Interop.SetWindowPos(
            _hwnd, IntPtr.Zero, 0, 0, 0, 0,
            Interop.SWP_NOMOVE | Interop.SWP_NOSIZE | Interop.SWP_NOZORDER
            | Interop.SWP_FRAMECHANGED | Interop.SWP_NOACTIVATE);

    }

    /// <summary>Rounded corners and dark chrome, as dwm.py does today.</summary>
    public void ApplyDwmChrome(bool dark)
    {
        var corner = (int)Interop.DWMWCP_ROUND;
        Interop.DwmSetWindowAttribute(
            _hwnd, Interop.DWMWA_WINDOW_CORNER_PREFERENCE, ref corner, sizeof(int));
        var useDark = dark ? 1 : 0;
        Interop.DwmSetWindowAttribute(
            _hwnd, Interop.DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDark, sizeof(int));
    }

    /// <summary>
    /// Register a system-wide Alt+key that invokes <paramref name="handler"/>.
    /// MOD_NOREPEAT matches the native hotkey runtime, so holding the keys down
    /// fires once rather than repeating.
    /// </summary>
    public bool RegisterAltHotkey(uint virtualKey, Action handler)
    {
        InstallSubclass();
        var id = _nextHotkeyId++;
        if (!Interop.RegisterHotKey(
                _hwnd, id, Interop.MOD_ALT | Interop.MOD_NOREPEAT, virtualKey))
        {
            return false;
        }
        _hotkeys[id] = handler;
        return true;
    }

    private void InstallSubclass()
    {
        if (_subclass is not null)
        {
            return;
        }
        _subclass = HandleMessage;
        _previousProcedure = Interop.SetWindowLongPtrW(
            _hwnd,
            Interop.GWLP_WNDPROC,
            System.Runtime.InteropServices.Marshal.GetFunctionPointerForDelegate(_subclass));
    }

    private IntPtr HandleMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        if (msg == Interop.WM_HOTKEY && _hotkeys.TryGetValue(wParam.ToInt32(), out var handler))
        {
            handler();
            return IntPtr.Zero;
        }

        // IsMaximizable=false only greys the caption button; double-clicking
        // the title bar still sends SC_MAXIMIZE. Swallow it so the window has
        // one size behaviour rather than two.
        if (msg == Interop.WM_SYSCOMMAND
            && (wParam.ToInt64() & 0xFFF0) == Interop.SC_MAXIMIZE)
        {
            return IntPtr.Zero;
        }

        return Interop.CallWindowProcW(_previousProcedure, hWnd, msg, wParam, lParam);
    }

    /// <summary>
    /// Repaint the caption as inactive.
    ///
    /// Showing the window redraws the frame but never sends WM_NCACTIVATE, so
    /// the frame is drawn from an activation flag nothing has updated. A
    /// WS_EX_NOACTIVATE window is never the foreground window, so its caption
    /// should always read inactive; this sets that explicitly once the window
    /// is back on screen.
    /// </summary>
    public void PaintCaptionInactive() =>
        Interop.SendMessageW(_hwnd, Interop.WM_NCACTIVATE, IntPtr.Zero, IntPtr.Zero);

    public void Dispose()
    {
        if (_subclass is null)
        {
            return;
        }
        foreach (var id in _hotkeys.Keys)
        {
            Interop.UnregisterHotKey(_hwnd, id);
        }
        _hotkeys.Clear();
        Interop.SetWindowLongPtrW(_hwnd, Interop.GWLP_WNDPROC, _previousProcedure);
        _subclass = null;
    }
}
