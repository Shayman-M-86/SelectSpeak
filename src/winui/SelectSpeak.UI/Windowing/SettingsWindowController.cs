using System;
using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;

namespace SelectSpeak.UI.Windowing;

/// <summary>
/// How the settings window behaves.
///
/// Deliberately not the player's behaviour. The player must never take focus,
/// because it floats over the app being read; settings is a window the user
/// deals with directly, so it activates normally and is not always on top. It
/// is also a fixed size, where the player can be resized to suit the text.
/// What the two share is hiding rather than closing, so reopening it does not
/// rebuild the window or lose what the backend has already sent.
/// </summary>
public sealed class SettingsWindowController
{
    private readonly Window _window;
    private readonly AppWindow _appWindow;
    private readonly OverlappedPresenter _presenter;

    // False until the window has been moved back from where Prepare parked it.
    private bool _positioned;

    public SettingsWindowController(Window window)
    {
        _window = window;
        _appWindow = window.AppWindow;

        _presenter = OverlappedPresenter.Create();
        _appWindow.SetPresenter(_presenter);

        // A fixed list of settings, so the window is a fixed size: resizing it
        // could only add empty space or hide rows behind a scrollbar.
        _presenter.IsResizable = false;
        _presenter.IsMaximizable = false;
        _presenter.IsMinimizable = false;

        _appWindow.Resize(new SizeInt32(520, 620));

        ApplyApplicationIcon();

        _appWindow.Closing += (_, args) =>
        {
            args.Cancel = true;
            Hide();
            // The player is restored by posting its hotkey message, so it
            // already lands after this close finishes rather than during it.
            Dismissed?.Invoke();
        };
    }

    /// <summary>Raised when the window is closed, so a caller can restore
    /// whatever it hid to make room.</summary>
    public event Action? Dismissed;

    /// <summary>
    /// Realise the window without the user seeing it.
    ///
    /// A window shown for the first time paints its default background before
    /// Mica is applied, which reads as a white flash. Doing that first paint at
    /// startup, parked off screen, means the first real Show has nothing left
    /// to paint. The move also has to happen before the activation, or the
    /// flash simply happens at startup instead.
    /// </summary>
    public void Prepare()
    {
        _appWindow.Move(new PointInt32(-32000, -32000));
        _window.Activate();
        _appWindow.Hide();
        _positioned = false;
    }

    /// <summary>Show the window, bringing it to the front if it was already open.</summary>
    public void Show()
    {
        // Back to where it belongs, after Prepare parked it off screen.
        if (!_positioned)
        {
            CentreOnPlayerMonitor();
            _positioned = true;
        }

        _window.Activate();
        _appWindow.Show();
        _presenter.Restore();
        BringToFront();
    }

    /// <summary>
    /// Show the application icon on this window and its taskbar button.
    ///
    /// Unlike the player, settings is an ordinary window, so it appears on the
    /// taskbar. ApplicationIcon only stamps the icon into the executable's
    /// resources; a WinUI AppWindow does not adopt that on its own and would
    /// otherwise show the generic default. Failing to set it costs nothing but
    /// the icon, so a failure here must never stop the window opening.
    /// </summary>
    private void ApplyApplicationIcon()
    {
        try
        {
            var module = Interop.GetModuleHandleW(null);
            var buffer = new char[260];
            var length = Interop.GetModuleFileNameW(module, buffer, (uint)buffer.Length);
            if (length == 0)
            {
                return;
            }

            var executable = new string(buffer, 0, (int)length);
            var icon = Interop.ExtractIconW(module, executable, 0);
            // ExtractIcon returns 1 when the file holds no icons at all.
            if (icon == IntPtr.Zero || icon == new IntPtr(1))
            {
                return;
            }

            _appWindow.SetIcon(Win32Interop.GetIconIdFromIcon(icon));
        }
        catch (Exception)
        {
            // An unavailable icon is cosmetic; the window still works.
        }
    }

    /// <summary>Put the window in the middle of the screen it will appear on.</summary>
    private void CentreOnPlayerMonitor()
    {
        var area = DisplayArea.GetFromWindowId(_appWindow.Id, DisplayAreaFallback.Primary).WorkArea;
        _appWindow.Move(new PointInt32(
            area.X + ((area.Width - _appWindow.Size.Width) / 2),
            area.Y + ((area.Height - _appWindow.Size.Height) / 2)));
    }

    public void Hide() => _appWindow.Hide();

    /// <summary>
    /// Put the window in front and give it focus.
    ///
    /// Activate is not enough here. The gear that opens this sits on the
    /// player, which is WS_EX_NOACTIVATE and therefore never the foreground
    /// window - and Windows only lets the process that owns the foreground
    /// window set a new one. So the request is refused and the window opens
    /// behind everything.
    ///
    /// Briefly attaching to the input state of whichever thread does own the
    /// foreground makes this process count as the caller, which is the
    /// documented way out of that rule.
    /// </summary>
    private void BringToFront()
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(_window);
        var foreground = GetForegroundWindow();
        if (foreground == hwnd)
        {
            return;
        }

        var us = GetCurrentThreadId();
        var them = GetWindowThreadProcessId(foreground, IntPtr.Zero);

        var attached = them != 0 && them != us && AttachThreadInput(us, them, true);
        try
        {
            SetForegroundWindow(hwnd);
            BringWindowToTop(hwnd);
            SetActiveWindow(hwnd);
        }
        finally
        {
            if (attached)
            {
                AttachThreadInput(us, them, false);
            }
        }
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern IntPtr SetActiveWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr processId);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AttachThreadInput(uint attachTo, uint attachFrom, bool attach);
}
