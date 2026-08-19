using System;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;

namespace SelectSpeak.UI.Windowing;

/// <summary>
/// How the player window behaves, so the view never deals with a presenter or
/// an HWND.
///
/// There is one behaviour and no configuration: the window is a floating,
/// always-on-top panel that cannot be minimised or maximised, never steals
/// focus, and hides rather than closes. Alt+A and the close button both toggle
/// that hidden state.
/// </summary>
public sealed class WindowController : IDisposable
{
    // 'A' - Alt+A toggles the window.
    private const uint ToggleVirtualKey = 0x41;

    private readonly AppWindow _appWindow;
    private readonly OverlappedPresenter _presenter;
    private readonly OverlayWindow _overlay;

    public WindowController(Window window)
    {
        _appWindow = window.AppWindow;

        // OverlappedPresenter is the one that exposes exact sizes and lets the
        // minimise and maximise buttons be turned off.
        _presenter = OverlappedPresenter.Create();
        _appWindow.SetPresenter(_presenter);

        _presenter.IsResizable = true;
        _presenter.IsMaximizable = false;
        _presenter.IsMinimizable = false;
        _presenter.IsAlwaysOnTop = true;
        _presenter.PreferredMinimumWidth = 320;
        _presenter.PreferredMinimumHeight = 180;

        _appWindow.Resize(new SizeInt32(720, 470));

        _overlay = new OverlayWindow(window);
        // Clicking the player must not pull focus from the app being read.
        //
        // This is also why the window looks permanently unfocused: Mica has
        // separate active and inactive appearances and follows the foreground
        // window, and a no-activate window is never the foreground window. The
        // flat backdrop and greyed caption are the cost of not stealing focus.
        _overlay.EnableNoActivate();
        _overlay.ApplyDwmChrome(dark: true);
        _overlay.RegisterAltHotkey(ToggleVirtualKey, Toggle);

        // Closing is the same action as the hotkey: the window hides and the
        // process keeps running. AppWindow.Closing covers the caption button,
        // Alt+F4 and the system menu alike.
        _appWindow.Closing += (_, args) =>
        {
            args.Cancel = true;
            Hide();
        };
    }

    /// <summary>Whether the window is currently hidden.</summary>
    public bool IsHidden { get; private set; }

    /// <summary>
    /// Do exactly what pressing Alt+A does, by posting the same message the
    /// key press posts.
    ///
    /// Anything else that wants to show or hide the player goes through here,
    /// so there is one code path with one set of repainting behaviour rather
    /// than a second one that merely calls the same methods from a different
    /// point in the frame.
    /// </summary>
    public void PressToggleHotkey() => _overlay.PressHotkey(ToggleVirtualKey);

    /// <summary>Show or hide the window - what Alt+A and the close button do.</summary>
    public void Toggle()
    {
        if (IsHidden)
        {
            Show();
        }
        else
        {
            Hide();
        }
    }

    public void Show()
    {
        _appWindow.Show();
        IsHidden = false;
        // The frame is repainted by the show itself, from an activation flag
        // that nothing updates, so the caption is corrected afterwards.
        _overlay.PaintCaptionInactive();
    }

    public void Hide()
    {
        _appWindow.Hide();
        IsHidden = true;
    }

    public void Dispose() => _overlay.Dispose();
}
