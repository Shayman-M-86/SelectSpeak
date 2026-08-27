using System;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using SelectSpeak.UI.Input;

namespace SelectSpeak.UI.Views;

/// <summary>
/// Records a shortcut and confirms it.
///
/// The keyboard hook runs in this process, beside the dialog it updates, so a
/// keystroke reaches the display directly instead of crossing to the backend
/// and back. The backend hears about it once, when the user confirms.
/// </summary>
public sealed class HotkeyDialog
{
    // Fixed, so the dialog does not resize as the preview and hint change.
    // Wide enough for the longest hint to fit two lines without clipping.
    private const double ContentWidth = 380;

    private readonly TextBlock _preview = new()
    {
        FontSize = 20,
        HorizontalAlignment = HorizontalAlignment.Center,
        VerticalAlignment = VerticalAlignment.Center,
        TextAlignment = TextAlignment.Center,
    };

    // A fixed height. MinHeight alone is not enough: the hints differ in
    // length, so a one-line message and a wrapped two-line one would give the
    // dialog different heights and it would jump as the text changed. Two
    // lines' worth plus slack, so a wrap is never clipped.
    private readonly TextBlock _hint = new()
    {
        HorizontalAlignment = HorizontalAlignment.Stretch,
        TextAlignment = TextAlignment.Center,
        TextWrapping = TextWrapping.Wrap,
        Height = 40,
        VerticalAlignment = VerticalAlignment.Top,
    };

    private readonly DispatcherQueue _dispatcher = DispatcherQueue.GetForCurrentThread();

    private ContentDialog? _dialog;
    private string _captured = string.Empty;

    /// <summary>
    /// Show the dialog and return the confirmed shortcut, or <c>null</c> if it
    /// was cancelled or nothing was recorded.
    /// </summary>
    /// <param name="owner">
    /// The window the dialog belongs to. Recording stops if it stops being the
    /// active window, because the hook swallows Alt+Tab and everything else -
    /// so a dialog left recording in the background could not be returned to.
    /// </param>
    /// <param name="current">The shortcut in force, shown until keys arrive.</param>
    public async Task<string?> ShowAsync(Window owner, string current)
    {
        var xamlRoot = owner.Content.XamlRoot;
        _captured = string.Empty;
        _preview.Text = string.IsNullOrEmpty(current) ? "Press a shortcut" : current;
        _preview.Foreground = (Brush)Application.Current.Resources["TextFillColorSecondaryBrush"];
        _hint.Text = "Press the keys for your shortcut, or Esc to cancel.";

        var capture = new Border
        {
            Background = (Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
            BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(4),
            Padding = new Thickness(16),
            // Fixed rather than minimum, so a long shortcut cannot make the
            // card taller than a short one.
            Height = 72,
            Child = _preview,
        };

        var panel = new StackPanel { Spacing = 12, Width = ContentWidth };
        panel.Children.Add(_hint);
        panel.Children.Add(capture);

        _dialog = new ContentDialog
        {
            XamlRoot = xamlRoot,
            Title = "Change shortcut",
            Content = panel,
            PrimaryButtonText = "Confirm",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            // Nothing has been recorded yet, so there is nothing to confirm.
            IsPrimaryButtonEnabled = false,
        };

        // The hook runs on the thread that installed it, but its callbacks can
        // arrive before the dialog's own layout work has finished, so every
        // update is marshalled onto the UI queue.
        using var recorder = new ShortcutRecorder();
        recorder.Preview += combo => Post(() => ShowPending(combo));
        recorder.Recorded += combo => Post(() => ShowRecorded(combo));
        recorder.Cancelled += () => Post(() => _dialog?.Hide());

        // Losing the window cancels the recording. The hook swallows Alt+Tab
        // and the Windows key, so a dialog still recording in the background
        // would leave no way of getting back to it.
        void OnActivated(object _, WindowActivatedEventArgs args)
        {
            if (args.WindowActivationState == WindowActivationState.Deactivated)
            {
                Post(() => _dialog?.Hide());
            }
        }

        owner.Activated += OnActivated;

        if (!recorder.Start())
        {
            _hint.Text = "The keyboard could not be captured. Close and try again.";
        }

        try
        {
            var result = await _dialog.ShowAsync();
            _dialog = null;
            return result == ContentDialogResult.Primary && _captured.Length > 0
                ? _captured
                : null;
        }
        finally
        {
            owner.Activated -= OnActivated;
            recorder.Stop();
        }
    }

    private void Post(Action action)
    {
        if (!_dispatcher.TryEnqueue(() => action()))
        {
            // The window is going away; there is nothing left to update.
        }
    }

    /// <summary>Show the modifiers held so far, while the shortcut is incomplete.</summary>
    private void ShowPending(string combo)
    {
        if (_dialog is null)
        {
            return;
        }

        _captured = string.Empty;
        _dialog.IsPrimaryButtonEnabled = false;
        _preview.Foreground = (Brush)Application.Current.Resources["TextFillColorSecondaryBrush"];

        if (combo.Length == 0)
        {
            _preview.Text = "Press a shortcut";
            _hint.Text = "Include Ctrl, Alt, Shift or the Windows key.";
            return;
        }

        // The trailing separator shows a trigger key is still expected.
        _preview.Text = Display(combo) + "+…";
        _hint.Text = "Now press the key to go with it.";
    }

    /// <summary>Hold a complete shortcut, ready to be confirmed.</summary>
    private void ShowRecorded(string combo)
    {
        if (_dialog is null)
        {
            return;
        }

        _captured = combo;
        _preview.Text = Display(combo);
        _preview.Foreground = (Brush)Application.Current.Resources["TextFillColorPrimaryBrush"];
        _hint.Text = "Confirm to keep it, or press a different shortcut.";
        _dialog.IsPrimaryButtonEnabled = true;
    }

    /// <summary>Render a shortcut the way Windows writes them: Ctrl+Shift+S.</summary>
    private static string Display(string hotkey) =>
        string.Join(
            "+",
            hotkey.Split('+').Select(part => part switch
            {
                "ctrl" => "Ctrl",
                "alt" => "Alt",
                "shift" => "Shift",
                "windows" => "Win",
                "page_up" => "Page Up",
                "page_down" => "Page Down",
                _ => part.Length == 1 ? part.ToUpperInvariant() : Capitalise(part),
            }));

    private static string Capitalise(string value) =>
        value.Length == 0 ? value : char.ToUpperInvariant(value[0]) + value[1..];
}
