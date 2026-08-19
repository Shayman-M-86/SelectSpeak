using Microsoft.UI;
using System;
using System.Collections.Generic;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using SelectSpeak.UI.Bridge;
using SelectSpeak.UI.Windowing;
using Windows.Foundation;

namespace SelectSpeak.UI.Views;

/// <summary>
/// The player window. It owns what appears inside the window; how the window
/// behaves is delegated to <see cref="WindowController"/>.
/// </summary>
public sealed partial class PlayerWindow : Window
{
    // Segoe Fluent Icons: the button shows the state, so playing shows a pause
    // glyph as the action available.
    private const string PauseGlyph = "";
    private const string PlayGlyph = "";

    private const string BulletPrefix = "• ";

    // Shown when there is nothing to read. Kept in step with the same wording
    // in PlayerWindow.xaml, which is what the window starts with.
    private const string PlaceholderText = "Select some text and press the read shortcut.";

    // How close to an edge the spoken word may get before the reader scrolls,
    // as a fraction of the visible height. Proportional rather than a pixel
    // count, so a short window scrolls sooner than a tall one instead of
    // scrolling on almost every word.
    private const double EdgeMarginFraction = 0.2;

    // Where the word lands after a scroll, as a fraction from the top. Near the
    // top, so most of the viewport holds what comes next and the reader is not
    // scrolling again immediately.
    private const double RestPositionFraction = 0.25;

    // How long the reader leaves the scroll alone after it has been moved by
    // hand, so looking back at an earlier line is not undone by the next word.
    private static readonly TimeSpan ManualScrollHold = TimeSpan.FromSeconds(5);

    private readonly IPlayerBridge _bridge;
    private readonly WindowController _controller;

    // Where each line begins, in the backend's string and in the rendered
    // content, which differ by one character per preceding line break.
    private readonly List<(int Backend, int Rendered)> _lineStarts = new();

    private string _text = string.Empty;
    private int _renderedLength;

    // Set while the reader is scrolling itself, so its own movement is not
    // mistaken for the user taking over.
    private bool _scrollingToWord;

    // When the user last moved the scroll by hand. Null once the hold has
    // expired and the reader has resumed following the spoken word.
    private DateTimeOffset? _manualScrollAt;

    public PlayerWindow(IPlayerBridge bridge)
    {
        this.InitializeComponent();

        Title = "SelectSpeak";

        // Draw into the caption area so the title row above is the title bar.
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);

        _controller = new WindowController(this);

        _bridge = bridge;
        // Pipe messages arrive on a background thread, so every render hops
        // back to the UI thread before touching a control.
        _bridge.MessageReceived += message =>
            DispatcherQueue.TryEnqueue(() => Apply(message));

    }

    /// <summary>
    /// Render one message from the backend.
    ///
    /// The view only draws what it is told: it never decides that playback has
    /// started or finished, it is informed.
    /// </summary>
    public void Apply(PlayerMessage message)
    {
        switch (message.Type)
        {
            case "set_text":
                SetText(message.Text ?? string.Empty);
                break;

            case "highlight_word":
                HighlightWord(message.Position, message.Length);
                break;

            case "set_shortcut":
                SetShortcut(message.Hotkey ?? string.Empty);
                break;

            case "set_playback":
                SetPlayback(message.Speaking, message.Paused);
                break;

            case "show":
                _controller.Show();
                break;

            case "hide":
                _controller.Hide();
                break;
        }
    }

    /// <summary>Whether the player is currently hidden.</summary>
    public bool IsHidden => _controller.IsHidden;

    /// <summary>
    /// Show or hide the player exactly as Alt+A does.
    ///
    /// This posts the hotkey's own message rather than calling Show or Hide,
    /// so the window changes state at the same point in the message loop that
    /// the key press would - which is what makes it repaint identically.
    /// </summary>
    public void ToggleAsHotkey() => _controller.PressToggleHotkey();

    /// <summary>
    /// Name the shortcut that starts a read, beside the settings button.
    ///
    /// This is the only message the player shows. Collapsed when empty, so the
    /// gear sits alone rather than beside a gap.
    /// </summary>
    private void SetShortcut(string hotkey)
    {
        ShortcutHint.Text = hotkey.Length > 0 ? $"{hotkey} to Read Selection" : string.Empty;
        ShortcutHint.Visibility = hotkey.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    /// <summary>
    /// Replace the reader contents.
    ///
    /// Paragraph spacing is a Margin rather than line spacing so the spoken-word
    /// highlight is the same size wherever the word falls, and a bullet gets a
    /// hanging indent so its wrapped lines align under the text.
    /// </summary>
    private void SetText(string text)
    {
        _text = text;
        Reader.Blocks.Clear();
        Reader.TextHighlighters.Clear();

        // New contents start at the top, rather than wherever the last read
        // had scrolled to. Flagged as the reader's own move, and any hold from
        // the previous passage is dropped: this text has not been scrolled.
        _manualScrollAt = null;
        // If the view does not actually move, no ViewChanged follows, so the
        // flag would stay set and swallow the user's next scroll.
        _scrollingToWord = ReaderScroll.ChangeView(null, 0, null, disableAnimation: true);

        // Each line break is dropped when the text becomes paragraphs, so a
        // TextRange index is not the backend's index: everything after a break
        // shifts left by one per break before it. This records where each line
        // starts in the backend's string alongside where it starts in the
        // rendered content, which is what HighlightWord maps between.
        _lineStarts.Clear();

        if (text.Trim().Length == 0)
        {
            // Nothing to read, so the reader goes back to the resting prompt
            // rather than showing an empty card.
            Reader.Blocks.Add(new Paragraph
            {
                Margin = new Thickness(0, 0, 0, 6),
                Inlines = { new Run { Text = PlaceholderText } },
            });
            _renderedLength = 0;
            return;
        }

        var backendStart = 0;
        var renderedStart = 0;
        foreach (var line in text.Split('\n'))
        {
            _lineStarts.Add((backendStart, renderedStart));
            backendStart += line.Length + 1; // + the '\n' that was removed.

            // Text almost always ends in a newline, which splits into a final
            // empty line. Rendering it adds a trailing empty paragraph, and a
            // highlight that ends flush against it faults inside the XAML
            // framework - which is what the last word of every read does.
            if (line.Length == 0)
            {
                continue;
            }

            var isBullet = line.StartsWith(BulletPrefix, StringComparison.Ordinal);
            Reader.Blocks.Add(new Paragraph
            {
                Margin = new Thickness(isBullet ? 14 : 0, 0, 0, 6),
                TextIndent = isBullet ? -14 : 0,
                Inlines = { new Run { Text = line } },
            });

            renderedStart += line.Length;
        }

        _renderedLength = renderedStart;
    }

    /// <summary>
    /// Paint the spoken word. Offsets index the same string the backend speaks,
    /// so highlighting stays aligned with the speech pipeline.
    /// </summary>
    private void HighlightWord(int position, int length)
    {
        Reader.TextHighlighters.Clear();
        if (length <= 0 || position < 0 || position >= _text.Length)
        {
            return;
        }

        var start = ToRenderedIndex(position);

        // A range that runs past the rendered content faults inside the XAML
        // framework rather than throwing, so the clamp is load-bearing: the
        // last word of the text ends beyond it once the line breaks are gone.
        var available = _renderedLength - start;
        if (available <= 0)
        {
            return;
        }

        var highlighter = new TextHighlighter
        {
            Background = (Brush)Application.Current.Resources["AccentFillColorDefaultBrush"],
            Foreground = (Brush)Application.Current.Resources["TextOnAccentFillColorPrimaryBrush"],
        };
        highlighter.Ranges.Add(new TextRange
        {
            StartIndex = start,
            Length = Math.Min(length, available),
        });
        Reader.TextHighlighters.Add(highlighter);

        KeepWordInView(start);
    }

    /// <summary>
    /// Scroll so the word being spoken stays readable.
    ///
    /// Only when it is about to leave the visible area, and then far enough
    /// that the following lines are visible too - scrolling it just inside the
    /// edge would mean scrolling again on the very next word. The thresholds
    /// are fractions of the viewport rather than fixed pixels, so this behaves
    /// the same whatever height the window is given.
    /// </summary>
    private void KeepWordInView(int renderedIndex)
    {
        if (IsManualScrollHeld())
        {
            return; // The user is reading somewhere else for the moment.
        }

        var viewport = ReaderScroll.ViewportHeight;
        if (viewport <= 0)
        {
            return; // Not laid out yet.
        }

        var word = CharacterRect(renderedIndex);
        if (word is null)
        {
            return;
        }

        // Where the word sits relative to what is on screen.
        var top = word.Value.Top - ReaderScroll.VerticalOffset;
        var bottom = top + word.Value.Height;

        // A band at each edge that counts as "about to leave".
        var margin = viewport * EdgeMarginFraction;
        if (top >= margin && bottom <= viewport - margin)
        {
            return; // Comfortably in view; leave the scroll alone.
        }

        // Put the word near the top, leaving the rest of the viewport ahead of
        // it, so reading continues for a while before scrolling again.
        var target = word.Value.Top - (viewport * RestPositionFraction);

        // Flagged, so the resulting ViewChanged is not read as the user
        // scrolling and does not start a hold against the reader itself. A
        // refused move raises no event, so the flag must not be left set.
        _scrollingToWord = ReaderScroll.ChangeView(
            null, Math.Max(0, target), null, disableAnimation: false);
    }

    /// <summary>
    /// Whether the scroll was moved by hand recently enough to leave it alone.
    /// </summary>
    private bool IsManualScrollHeld()
    {
        if (_manualScrollAt is null)
        {
            return false;
        }

        if (DateTimeOffset.UtcNow - _manualScrollAt.Value < ManualScrollHold)
        {
            return true;
        }

        // Expired, so the reader takes the scroll back.
        _manualScrollAt = null;
        return false;
    }

    /// <summary>
    /// Note a scroll the reader did not make, so following the spoken word
    /// pauses until the hold expires.
    /// </summary>
    private void OnReaderScrolled(object sender, ScrollViewerViewChangedEventArgs args)
    {
        if (args.IsIntermediate)
        {
            // Mid-gesture; the settled position is what matters.
            return;
        }

        if (_scrollingToWord)
        {
            _scrollingToWord = false;
            return;
        }

        _manualScrollAt = DateTimeOffset.UtcNow;
    }

    /// <summary>
    /// The bounds of one character, in the reader's own coordinates, or null if
    /// it cannot be resolved.
    /// </summary>
    private Rect? CharacterRect(int renderedIndex)
    {
        try
        {
            var pointer = Reader.ContentStart?.GetPositionAtOffset(
                renderedIndex, LogicalDirection.Forward);
            return pointer?.GetCharacterRect(LogicalDirection.Forward);
        }
        catch (ArgumentException)
        {
            // An offset the layout does not accept; not worth scrolling for.
            return null;
        }
    }

    /// <summary>
    /// Convert a backend character offset into the index the reader uses.
    ///
    /// They diverge because building paragraphs drops the line breaks, so an
    /// offset on the third line is two characters ahead of where that text
    /// actually sits in the rendered content.
    /// </summary>
    private int ToRenderedIndex(int position)
    {
        var rendered = position;
        foreach (var (backend, renderedStart) in _lineStarts)
        {
            if (backend > position)
            {
                break;
            }
            rendered = renderedStart + (position - backend);
        }
        return rendered;
    }

    /// <summary>
    /// Report the user's intent. The backend decides what happens and sends
    /// back a set_playback message; the UI never changes its own state here.
    /// </summary>
    private async void OnPlayPause(object sender, RoutedEventArgs e) =>
        await _bridge.SendAsync("toggle_playback");

    private async void OnStop(object sender, RoutedEventArgs e) =>
        await _bridge.SendAsync("stop");

    private async void OnSettings(object sender, RoutedEventArgs e) =>
        await _bridge.SendAsync("settings");

    /// <summary>
    /// Put the transport button and activity bar into the playing or paused
    /// state. Playing is called out in green; paused stays with the default
    /// foreground so only one state draws attention.
    /// </summary>
    /// <summary>
    /// Apply a playback state.
    ///
    /// Stopped and paused are different: pausing keeps the spoken word marked,
    /// because reading resumes from there, while stopping or finishing leaves
    /// nothing being spoken and so nothing highlighted.
    /// </summary>
    private void SetPlayback(bool speaking, bool paused)
    {
        SetPlaying(speaking && !paused);

        // Both transport buttons act on playback, so neither means anything
        // once there is none: pausing and stopping are equally moot. Collapsed
        // rather than disabled, so the row closes up around them and only the
        // shortcut label and gear remain.
        var transport = speaking ? Visibility.Visible : Visibility.Collapsed;
        PlayPauseButton.Visibility = transport;
        StopButton.Visibility = transport;

        if (!speaking)
        {
            // Nothing is being read, so no word is the current one.
            Reader.TextHighlighters.Clear();
        }
    }

    private void SetPlaying(bool playing)
    {
        PlayPauseLabel.Text = playing ? "Playing" : "Paused";
        PlayPauseIcon.Glyph = playing ? PauseGlyph : PlayGlyph;

        if (playing)
        {
            // A muted system green rather than a raw one, so it sits calmly on
            // the dark surface and follows the theme.
            PlayPauseLabel.Foreground =
                (Brush)Application.Current.Resources["SystemFillColorSuccessBrush"];
        }
        else
        {
            // Clear the local value rather than assigning a colour, so the
            // button's own style drives the foreground again - including its
            // dulled rest state and the brighter hover state. Assigning a brush
            // here would pin the label to one colour permanently.
            PlayPauseLabel.ClearValue(TextBlock.ForegroundProperty);
        }

        // Collapse the bar when idle rather than only stopping it: a stopped
        // ProgressBar still draws its track, which reads as a stray line.
        ActivityBar.IsIndeterminate = playing;
        ActivityBar.Visibility = playing ? Visibility.Visible : Visibility.Collapsed;

    }
}
