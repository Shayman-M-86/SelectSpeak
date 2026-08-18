using System;
using System.Text.Json;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;
using Windows.UI;

namespace SelectSpeak.UI;

/// <summary>
/// A renderer for the existing PlayerWindow contract. It holds no application
/// state of its own: every decision arrives from Python as a message, and every
/// button press goes back as an intent.
/// </summary>
public sealed partial class MainWindow : Window
{
    // Segoe Fluent Icons, matching the glyphs the Tk player already uses.
    private const string GlyphPlay = "\uE768";
    private const string GlyphPause = "\uE769";
    private const string GlyphReplay = "\uE72C";

    private readonly PlayerBridge _bridge;
    private readonly DispatcherQueue _dispatcher;
    private readonly OverlappedPresenter _presenter;

    private string _text = string.Empty;
    private bool _speaking;
    private bool _paused;

    private SolidColorBrush? _highlightBrush;
    private SolidColorBrush? _highlightForeground;

    public MainWindow(PlayerBridge bridge)
    {
        InitializeComponent();
        _bridge = bridge;
        _dispatcher = DispatcherQueue.GetForCurrentThread();

        Title = "SelectSpeak";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(TitleBar);

        // OverlappedPresenter is what gives real control: an exact size plus
        // min/max bounds. CompactOverlay honours Resize() too, but its
        // InitialSize only applies when the presenter is set, so it cannot be
        // driven from Python the way the reader needs.
        _presenter = OverlappedPresenter.Create();
        _presenter.PreferredMinimumWidth = 420;
        _presenter.PreferredMinimumHeight = 200;
        AppWindow.SetPresenter(_presenter);
        AppWindow.Resize(new SizeInt32(760, 440));

        _bridge.MessageReceived += OnMessage;
        _bridge.ConnectionChanged += OnConnectionChanged;
    }

    private void OnConnectionChanged(bool connected) => _dispatcher.TryEnqueue(() =>
    {
        if (!connected)
        {
            StatusText.Text = "Disconnected from SelectSpeak. Reconnecting…";
        }
    });

    private void OnMessage(JsonElement message) => _dispatcher.TryEnqueue(() =>
    {
        if (!message.TryGetProperty("type", out var typeElement))
        {
            return;
        }

        switch (typeElement.GetString())
        {
            case "set_text":
                _text = message.TryGetProperty("text", out var text) ? text.GetString() ?? "" : "";
                RenderText(null, 0);
                ApplyPlaybackState();
                break;

            case "highlight_word":
                RenderText(
                    message.GetProperty("position").GetInt32(),
                    message.GetProperty("length").GetInt32());
                break;

            case "set_status":
                StatusText.Text = message.TryGetProperty("text", out var status)
                    ? status.GetString() ?? ""
                    : "";
                break;

            case "set_playback":
                _speaking = message.TryGetProperty("speaking", out var speaking) && speaking.GetBoolean();
                _paused = message.TryGetProperty("paused", out var paused) && paused.GetBoolean();
                ApplyPlaybackState();
                break;

            case "show":
                AppWindow.Show();
                break;

            case "hide":
                AppWindow.Hide();
                break;

            case "resize":
                AppWindow.Resize(new SizeInt32(
                    message.GetProperty("width").GetInt32(),
                    message.GetProperty("height").GetInt32()));
                break;

            case "set_chrome":
                var border = !message.TryGetProperty("border", out var b) || b.GetBoolean();
                var titleBar = !message.TryGetProperty("title_bar", out var tb) || tb.GetBoolean();
                _presenter.SetBorderAndTitleBar(border, titleBar);
                break;

            case "set_resizable":
                _presenter.IsResizable =
                    !message.TryGetProperty("resizable", out var rz) || rz.GetBoolean();
                _presenter.IsMaximizable = _presenter.IsResizable;
                break;

            case "set_always_on_top":
                _presenter.IsAlwaysOnTop =
                    message.TryGetProperty("on_top", out var ot) && ot.GetBoolean();
                break;
        }
    });

    private void ApplyPlaybackState()
    {
        BusyRing.IsActive = _speaking && !_paused;
        StopButton.IsEnabled = _speaking;
        PlayButton.IsEnabled = _speaking || _text.Length > 0;

        if (_speaking && !_paused)
        {
            PlayLabel.Text = "Pause";
            PlayIcon.Glyph = GlyphPause;
        }
        else if (_speaking)
        {
            PlayLabel.Text = "Resume";
            PlayIcon.Glyph = GlyphPlay;
        }
        else
        {
            PlayLabel.Text = "Replay";
            PlayIcon.Glyph = GlyphReplay;
        }
    }

    /// <summary>
    /// Rebuild the reader, giving the spoken word its own Run.
    ///
    /// A Run's background covers exactly its glyphs, and paragraph spacing is a
    /// Margin rather than line padding, so the highlight is the same box
    /// wherever the word falls - including the last word of a paragraph, which
    /// both the Tk and RichEdit readers needed special handling for.
    /// </summary>
    private void RenderText(int? highlightStart, int highlightLength)
    {
        _highlightBrush ??= new SolidColorBrush(
            (Color)Application.Current.Resources["SystemAccentColor"]);
        _highlightForeground ??= new SolidColorBrush(Colors.Black);

        Reader.Blocks.Clear();

        var offset = 0;
        foreach (var line in _text.Split('\n'))
        {
            var isBullet = line.StartsWith("• ", StringComparison.Ordinal);
            var paragraph = new Paragraph
            {
                // Paragraph air as a margin: it never changes line height.
                Margin = new Thickness(isBullet ? 14 : 0, 0, 0, 6),
                TextIndent = isBullet ? -14 : 0,
            };

            var lineStart = offset;
            var lineEnd = offset + line.Length;
            var start = highlightStart ?? -1;

            if (highlightLength > 0 && start >= lineStart && start < lineEnd)
            {
                var localStart = start - lineStart;
                var localLength = Math.Min(highlightLength, line.Length - localStart);

                if (localStart > 0)
                {
                    paragraph.Inlines.Add(new Run { Text = line[..localStart] });
                }

                paragraph.Inlines.Add(new Run
                {
                    Text = line.Substring(localStart, localLength),
                    Foreground = _highlightForeground,
                });

                var tailStart = localStart + localLength;
                if (tailStart < line.Length)
                {
                    paragraph.Inlines.Add(new Run { Text = line[tailStart..] });
                }

                Reader.Blocks.Add(paragraph);
                HighlightRange(start, localLength);
            }
            else
            {
                if (line.Length > 0)
                {
                    paragraph.Inlines.Add(new Run { Text = line });
                }
                Reader.Blocks.Add(paragraph);
            }

            offset = lineEnd + 1;
        }

        if (highlightLength <= 0)
        {
            Reader.TextHighlighters.Clear();
        }
    }

    /// <summary>Paint the accent behind a character range of the document.</summary>
    private void HighlightRange(int start, int length)
    {
        Reader.TextHighlighters.Clear();
        var highlighter = new TextHighlighter
        {
            Background = _highlightBrush,
            Foreground = _highlightForeground,
        };
        highlighter.Ranges.Add(new TextRange { StartIndex = start, Length = length });
        Reader.TextHighlighters.Add(highlighter);
    }

    private async void OnRead(object sender, RoutedEventArgs e) =>
        await _bridge.SendAsync("read");

    private async void OnStop(object sender, RoutedEventArgs e) =>
        await _bridge.SendAsync("stop");

    private async void OnPlayPause(object sender, RoutedEventArgs e)
    {
        var intent = (_speaking, _paused) switch
        {
            (true, false) => "pause",
            (true, true) => "resume",
            _ => "play",
        };
        await _bridge.SendAsync(intent);
    }
}
