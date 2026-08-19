using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
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
        if (message.Type == "voice_error")
        {
            VoiceError.Message = message.Text ?? "This voice could not be used.";
            VoiceError.IsOpen = true;
            return;
        }

        if (message.Type == "hotkey_error")
        {
            HotkeyError.Message = message.Text ?? "That shortcut could not be used.";
            HotkeyError.IsOpen = true;
            return;
        }

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

            if (message.Voices is { Count: > 0 })
            {
                FillVoices(message.Voices, message.VoiceKey);
            }
        }
        finally
        {
            _applying = false;
        }
    }

    /// <summary>
    /// Rebuild the voice list, grouped by engine.
    ///
    /// A ComboBox has no nested items, so each group contributes a disabled
    /// heading followed by its voices - the same shape the Tk menu uses.
    /// </summary>
    private void FillVoices(IReadOnlyList<VoiceChoice> voices, string? selectedKey)
    {
        _applying = true;
        try
        {
            VoicePicker.Items.Clear();

            var group = string.Empty;
            foreach (var voice in voices)
            {
                if (voice.Group != group)
                {
                    group = voice.Group;
                    VoicePicker.Items.Add(new ComboBoxItem
                    {
                        Content = group,
                        IsEnabled = false,
                        // A heading, not a choice, so it reads as a label.
                        FontSize = 12,
                    });
                }

                var item = new ComboBoxItem { Content = voice.Label, Tag = voice.Key };
                VoicePicker.Items.Add(item);

                if (voice.Key == selectedKey)
                {
                    VoicePicker.SelectedItem = item;
                }
            }
        }
        finally
        {
            _applying = false;
        }
    }

    private async void OnVoiceSelected(object sender, SelectionChangedEventArgs e)
    {
        if (_applying || VoicePicker.SelectedItem is not ComboBoxItem { Tag: string key })
        {
            return;
        }

        // A fresh attempt, so any complaint about the last one is stale.
        VoiceError.IsOpen = false;

        await _bridge.SendAsync("select_voice", new Dictionary<string, string> { ["voice"] = key });
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
    private void OnCaptureHotkey(object sender, RoutedEventArgs e) =>
        _ = RecordShortcutAsync(HotkeyValue, "set_hotkey");

    private void OnCaptureOcrHotkey(object sender, RoutedEventArgs e) =>
        _ = RecordShortcutAsync(OcrHotkeyValue, "set_ocr_hotkey");

    /// <summary>
    /// Record a shortcut and report the one the user confirmed.
    ///
    /// Both shortcuts record identically, differing only in which value the
    /// dialog opens on and which intent carries the result, so the recording
    /// itself lives here once. The guard is shared deliberately: the hook
    /// swallows keys system-wide, and two dialogs competing for it would leave
    /// the keyboard captured by whichever closed last.
    /// </summary>
    private async Task RecordShortcutAsync(TextBlock display, string intent)
    {
        if (_recording)
        {
            return;
        }

        _recording = true;
        try
        {
            // A fresh attempt, so any complaint about the last one is stale.
            HotkeyError.IsOpen = false;

            // The dialog owns the keyboard hook for as long as it is open, so
            // the backend is not involved until there is a result to report.
            var chosen = await new HotkeyDialog().ShowAsync(this, display.Text);
            if (chosen is not null)
            {
                await _bridge.SendAsync(
                    intent,
                    new Dictionary<string, string> { ["hotkey"] = chosen });
            }
        }
        finally
        {
            _recording = false;
        }
    }
}
