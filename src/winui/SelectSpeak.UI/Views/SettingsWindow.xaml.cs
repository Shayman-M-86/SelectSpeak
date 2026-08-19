using System;
using System.Collections.Generic;
using Microsoft.UI.Xaml;
using SelectSpeak.UI.Bridge;
using SelectSpeak.UI.Windowing;

namespace SelectSpeak.UI.Views;

/// <summary>
/// The settings window.
///
/// It holds no state of its own: every switch reports an intent and waits to be
/// told the new value, because the settings live in the Python config and are
/// persisted there. That round trip is what makes a toggle stick.
/// </summary>
public sealed partial class SettingsWindow : Window
{
    private readonly IPlayerBridge _bridge;
    private readonly SettingsWindowController _controller;

    // Guards against a second dialog while one is already recording.
    private bool _recording;

    // Set while the backend's values are being written into the switches.
    // Assigning IsOn raises Toggled just as a click does, and without this the
    // window would report a change for every setting the moment it opened.
    private bool _applying;

    public SettingsWindow(IPlayerBridge bridge)
    {
        this.InitializeComponent();

        Title = "SelectSpeak Settings";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);

        _bridge = bridge;
        _controller = new SettingsWindowController(this);
    }

    /// <summary>Raised when the window is closed.</summary>
    public event Action? Dismissed
    {
        add => _controller.Dismissed += value;
        remove => _controller.Dismissed -= value;
    }

    /// <summary>
    /// Realise the window off screen, so the first real Show has nothing left
    /// to paint. Called once at startup.
    /// </summary>
    public void Prepare() => _controller.Prepare();

    /// <summary>Show the window, bringing it forward if it is already open.</summary>
    public void ShowWindow() => _controller.Show();

    /// <summary>
    /// Write the backend's settings into the controls.
    ///
    /// Only the fields a <c>show_settings</c> or <c>set_settings</c> message
    /// carries are applied; the window never infers a value it was not sent.
    /// </summary>
    public void Apply(PlayerMessage message)
    {
        _applying = true;
        try
        {
            AutoHideToggle.IsOn = message.AutoHide;
            ClipboardToggle.IsOn = message.ClipboardMode;
            DebugToggle.IsOn = message.DebugEnabled;

            if (!string.IsNullOrEmpty(message.Hotkey))
            {
                HotkeyValue.Text = message.Hotkey;
            }

            if (!string.IsNullOrEmpty(message.OcrHotkey))
            {
                OcrHotkeyValue.Text = message.OcrHotkey;
            }

            if (!string.IsNullOrEmpty(message.Voice))
            {
                VoiceValue.Text = message.Voice;
            }
        }
        finally
        {
            _applying = false;
        }
    }

    private async void OnAutoHideToggled(object sender, RoutedEventArgs e)
    {
        if (!_applying)
        {
            await _bridge.SendAsync("toggle_auto_hide");
        }
    }

    private async void OnClipboardToggled(object sender, RoutedEventArgs e)
    {
        if (!_applying)
        {
            await _bridge.SendAsync("toggle_clipboard");
        }
    }

    private async void OnDebugToggled(object sender, RoutedEventArgs e)
    {
        if (!_applying)
        {
            await _bridge.SendAsync("toggle_debug");
        }
    }

    /// <summary>
    /// Record a new shortcut and report the one the user confirmed.
    ///
    /// The dialog installs its own keyboard hook, which swallows keys
    /// system-wide, so a shortcut can use combinations another application or
    /// Windows itself would otherwise claim. The backend hears about it once,
    /// on Confirm, and remains the only thing that binds it.
    /// </summary>
    private async void OnCaptureHotkey(object sender, RoutedEventArgs e)
    {
        if (_recording)
        {
            return;
        }

        _recording = true;
        try
        {
            // The dialog owns the keyboard hook for as long as it is open, so
            // the backend is not involved until there is a result to report.
            var chosen = await new HotkeyDialog().ShowAsync(Content.XamlRoot, HotkeyValue.Text);
            if (chosen is not null)
            {
                await _bridge.SendAsync(
                    "set_hotkey",
                    new Dictionary<string, string> { ["hotkey"] = chosen });
            }
        }
        finally
        {
            _recording = false;
        }
    }
}
