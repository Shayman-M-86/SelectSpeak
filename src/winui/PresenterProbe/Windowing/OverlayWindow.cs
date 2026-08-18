using System;
using Microsoft.UI.Xaml;

namespace PresenterProbe.Windowing;

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

        FocusLog.Start(_hwnd);
        FocusLog.Write("WS_EX_NOACTIVATE applied", _hwnd);
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
            FocusLog.Write($"hotkey id={wParam.ToInt32()}", hWnd);
            handler();
            return IntPtr.Zero;
        }

        LogFocusMessage(msg, wParam, hWnd);

        // IsMaximizable=false only greys the caption button; double-clicking
        // the title bar still sends SC_MAXIMIZE. Swallow it so the window has
        // one size behaviour rather than two.
        if (msg == Interop.WM_SYSCOMMAND
            && (wParam.ToInt64() & 0xFFF0) == Interop.SC_MAXIMIZE)
        {
            FocusLog.Write("SC_MAXIMIZE blocked", hWnd);
            return IntPtr.Zero;
        }


        return Interop.CallWindowProcW(_previousProcedure, hWnd, msg, wParam, lParam);
    }

    /// <summary>
    /// Report the messages that decide whether the window looks focused.
    /// WM_NCACTIVATE is the one that actually paints the title bar: wParam 0
    /// draws it inactive (greyed), 1 draws it active.
    /// </summary>
    private static void LogFocusMessage(uint msg, IntPtr wParam, IntPtr hWnd)
    {
        switch (msg)
        {
            case Interop.WM_ACTIVATE:
                // LOWORD 0 = WA_INACTIVE, 1 = WA_ACTIVE, 2 = WA_CLICKACTIVE.
                var how = (wParam.ToInt64() & 0xFFFF) switch
                {
                    0 => "inactive",
                    1 => "active",
                    2 => "click-active",
                    _ => "?",
                };
                FocusLog.Write($"WM_ACTIVATE {how}", hWnd);
                break;
            case Interop.WM_NCACTIVATE:
                FocusLog.Write(
                    $"WM_NCACTIVATE incoming={(wParam == IntPtr.Zero ? "GREY" : "ACTIVE")}",
                    hWnd);
                break;
            case Interop.WM_ACTIVATEAPP:
                FocusLog.Write(
                    $"WM_ACTIVATEAPP app={(wParam == IntPtr.Zero ? "left" : "entered")}",
                    hWnd);
                break;
            case Interop.WM_MOUSEACTIVATE:
                FocusLog.Write("WM_MOUSEACTIVATE click", hWnd);
                break;
            case Interop.WM_SETFOCUS:
                FocusLog.Write("WM_SETFOCUS", hWnd);
                break;
            case Interop.WM_KILLFOCUS:
                FocusLog.Write("WM_KILLFOCUS", hWnd);
                break;

            // Double-clicking the caption sends this; it is what maximises the
            // window even though IsMaximizable is false.
            case Interop.WM_NCLBUTTONDBLCLK:
                FocusLog.Write("WM_NCLBUTTONDBLCLK caption dbl-click", hWnd);
                break;

            case Interop.WM_SYSCOMMAND:
                var command = wParam.ToInt64() & 0xFFF0;
                var name = command switch
                {
                    Interop.SC_MAXIMIZE => "MAXIMIZE",
                    Interop.SC_RESTORE => "RESTORE",
                    Interop.SC_MINIMIZE => "MINIMIZE",
                    Interop.SC_MOVE => "MOVE",
                    Interop.SC_SIZE => "SIZE",
                    Interop.SC_CLOSE => "CLOSE",
                    _ => $"0x{command:X}",
                };
                FocusLog.Write($"WM_SYSCOMMAND {name}", hWnd);
                break;

            case Interop.WM_SIZE:
                var state = wParam.ToInt64() switch
                {
                    Interop.SIZE_RESTORED => "restored",
                    Interop.SIZE_MINIMIZED => "minimized",
                    Interop.SIZE_MAXIMIZED => "MAXIMIZED",
                    _ => "?",
                };
                FocusLog.Write($"WM_SIZE {state}", hWnd);
                break;

            // A click in the client area - step 7 of the repro.
            case Interop.WM_LBUTTONDOWN:
                FocusLog.Write("WM_LBUTTONDOWN content click", hWnd);
                break;

            case Interop.WM_SHOWWINDOW:
                FocusLog.Write(
                    $"WM_SHOWWINDOW {(wParam == IntPtr.Zero ? "hiding" : "showing")}", hWnd);
                break;


            // Repainting the frame is what actually redraws the caption, so
            // this shows whether a stale active look is simply never repainted.
            case Interop.WM_NCPAINT:
                FocusLog.Write("WM_NCPAINT frame repaint", hWnd);
                break;
        }
    }

    /// <summary>
    /// Repaint the caption as inactive.
    ///
    /// Showing the window redraws the frame (WM_NCPAINT) but never sends
    /// WM_NCACTIVATE, so the frame is drawn from an activation flag nothing has
    /// updated. Because a WS_EX_NOACTIVATE window is never the foreground
    /// window, its caption should always read inactive - so it is set here
    /// explicitly once the window is back on screen.
    /// </summary>
    public void PaintCaptionInactive()
    {
        Interop.SendMessageW(_hwnd, Interop.WM_NCACTIVATE, IntPtr.Zero, IntPtr.Zero);
        FocusLog.Write("forced caption inactive", _hwnd);
    }

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
