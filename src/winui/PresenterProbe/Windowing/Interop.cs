using System;
using System.Runtime.InteropServices;

namespace PresenterProbe.Windowing;

/// <summary>
/// The Win32 the player window needs. A WinUI Window is a real top-level HWND,
/// so these apply exactly as they do to the current Tk window.
/// </summary>
internal static class Interop
{
    public const int GWL_EXSTYLE = -20;

    public const int WS_EX_NOACTIVATE = 0x08000000;

    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_NOZORDER = 0x0004;
    public const uint SWP_FRAMECHANGED = 0x0020;
    public const uint SWP_NOACTIVATE = 0x0010;

    // DWM attributes for rounded corners and dark chrome.
    public const uint DWMWA_USE_IMMERSIVE_DARK_MODE = 20;
    public const uint DWMWA_WINDOW_CORNER_PREFERENCE = 33;
    public const uint DWMWCP_ROUND = 2;

    // Hotkey registration, matching the native runtime's use of MOD_NOREPEAT.
    public const uint MOD_ALT = 0x0001;
    public const uint MOD_NOREPEAT = 0x4000;
    public const int WM_HOTKEY = 0x0312;

    // Subclassing, so the window can see WM_HOTKEY without a message loop.
    public const int GWLP_WNDPROC = -4;

    public delegate IntPtr WindowProcedure(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetWindowLongPtrW(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SetWindowLongPtrW(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

    [DllImport("user32.dll")]
    public static extern IntPtr CallWindowProcW(
        IntPtr previous, IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    // Messages that reveal how Windows is treating the window's focus.
    public const int WM_ACTIVATE = 0x0006;
    public const int WM_ACTIVATEAPP = 0x001C;
    public const int WM_NCACTIVATE = 0x0086;
    public const int WM_MOUSEACTIVATE = 0x0021;
    public const int WM_SETFOCUS = 0x0007;
    public const int WM_KILLFOCUS = 0x0008;

    // Non-client and sizing messages, to see maximise and restore happen.
    public const int WM_NCLBUTTONDBLCLK = 0x00A3;
    public const int WM_SYSCOMMAND = 0x0112;
    public const int WM_SIZE = 0x0005;
    public const int WM_LBUTTONDOWN = 0x0201;
    public const int WM_NCHITTEST = 0x0084;

    public const int SC_MAXIMIZE = 0xF030;
    public const int SC_RESTORE = 0xF120;
    public const int SC_MINIMIZE = 0xF020;
    public const int SC_MOVE = 0xF010;
    public const int SC_SIZE = 0xF000;
    public const int SC_CLOSE = 0xF060;

    public const int SIZE_RESTORED = 0;
    public const int SIZE_MINIMIZED = 1;
    public const int SIZE_MAXIMIZED = 2;

    public const int WM_SHOWWINDOW = 0x0018;
    public const int WM_WINDOWPOSCHANGED = 0x0047;
    public const int WM_SETTINGCHANGE = 0x001A;
    public const int WM_PAINT = 0x000F;
    public const int WM_NCPAINT = 0x0085;

    // Reading the frame's own active flag, which is what WM_NCPAINT draws from.
    public const uint DWMWA_NCRENDERING_ENABLED = 1;

    // DWM's own view of the frame. DWMWA_CAPTION_BUTTON_BOUNDS is irrelevant
    // here; what matters is whether DWM thinks the window is active, which is
    // what actually tints the caption on Windows 11.
    public const int GA_ROOT = 2;

    [DllImport("user32.dll")]
    public static extern IntPtr GetAncestor(IntPtr hWnd, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern IntPtr GetActiveWindow();

    [DllImport("user32.dll")]
    public static extern IntPtr GetFocus();

    [DllImport("kernel32.dll")]
    public static extern void SetLastError(uint dwErrCode);

    [DllImport("dwmapi.dll")]
    public static extern int DwmSetWindowAttribute(
        IntPtr hwnd, uint attribute, ref int value, int size);
}
