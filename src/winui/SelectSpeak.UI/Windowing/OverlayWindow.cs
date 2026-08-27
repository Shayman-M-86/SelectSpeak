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

    public OverlayWindow(Window window)
    {
        _hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
    }

    public IntPtr Handle => _hwnd;

    /// <summary>
    /// Clicking the window must not steal foreground from the app being read,
    /// and the player must not appear on the taskbar: it floats over the app
    /// being read, so it is chrome rather than a window to switch to.
    /// </summary>
    public void EnableNoActivate()
    {
        Interop.SetLastError(0);
        var stylePointer = Interop.GetWindowLongPtrW(_hwnd, Interop.GWL_EXSTYLE);
        ThrowIfZeroFailed(stylePointer, "GetWindowLongPtr(GWL_EXSTYLE) failed");
        var style = unchecked((int)stylePointer.ToInt64());

        // SetWindowLongPtr returns 0 both when the previous value was 0 and on
        // failure, so the last error is cleared first to tell them apart.
        SetWindowLongChecked(
            Interop.GWL_EXSTYLE,
            new IntPtr(style | Interop.WS_EX_NOACTIVATE | Interop.WS_EX_TOOLWINDOW),
            "SetWindowLongPtr(GWL_EXSTYLE) failed");

        if (!Interop.SetWindowPos(
                _hwnd, IntPtr.Zero, 0, 0, 0, 0,
                Interop.SWP_NOMOVE | Interop.SWP_NOSIZE | Interop.SWP_NOZORDER
                | Interop.SWP_FRAMECHANGED | Interop.SWP_NOACTIVATE))
        {
            var error = System.Runtime.InteropServices.Marshal.GetLastWin32Error();
            throw new System.ComponentModel.Win32Exception(error, "SetWindowPos failed");
        }
    }

    /// <summary>Rounded corners and dark chrome, as dwm.py does today.</summary>
    public void ApplyDwmChrome(bool dark)
    {
        var corner = (int)Interop.DWMWCP_ROUND;
        _ = Interop.DwmSetWindowAttribute(
            _hwnd, Interop.DWMWA_WINDOW_CORNER_PREFERENCE, ref corner, sizeof(int));
        var useDark = dark ? 1 : 0;
        _ = Interop.DwmSetWindowAttribute(
            _hwnd, Interop.DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDark, sizeof(int));
    }

    public void InstallSubclass()
    {
        if (_subclass is not null)
        {
            return;
        }
        var subclass = new Interop.WindowProcedure(HandleMessage);
        var procedure = System.Runtime.InteropServices.Marshal.GetFunctionPointerForDelegate(subclass);
        var previous = SetWindowLongChecked(
            Interop.GWLP_WNDPROC, procedure, "SetWindowLongPtr(GWLP_WNDPROC) failed");

        _previousProcedure = previous;
        _subclass = subclass;
    }

    private IntPtr HandleMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
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
        SetWindowLongChecked(
            Interop.GWLP_WNDPROC,
            _previousProcedure,
            "Restoring the window procedure failed");
        _subclass = null;
        _previousProcedure = IntPtr.Zero;
    }

    private IntPtr SetWindowLongChecked(int index, IntPtr value, string message)
    {
        Interop.SetLastError(0);
        var previous = Interop.SetWindowLongPtrW(_hwnd, index, value);
        ThrowIfZeroFailed(previous, message);
        return previous;
    }

    private static void ThrowIfZeroFailed(IntPtr result, string message)
    {
        if (result != IntPtr.Zero)
        {
            return;
        }

        var error = System.Runtime.InteropServices.Marshal.GetLastWin32Error();
        if (error != 0)
        {
            throw new System.ComponentModel.Win32Exception(error, message);
        }
    }
}
