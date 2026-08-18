using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using SelectSpeak.UI.Bridge;
using SelectSpeak.UI.Windowing;

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

    private readonly IPlayerBridge _bridge;
    private readonly WindowController _controller;
    private bool _playing;

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
            case "set_playback":
                SetPlaying(message.Speaking && !message.Paused);
                break;

            case "show":
                _controller.Show();
                break;

            case "hide":
                _controller.Hide();
                break;
        }
    }

    /// <summary>
    /// Show or hide the stop button.
    ///
    /// Collapsed rather than disabled, so the row closes up around it. Nothing
    /// calls this yet; it is here for the bridge to drive once playback state
    /// comes from the backend.
    /// </summary>
    public void SetStopVisible(bool visible) =>
        StopButton.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;

    /// <summary>
    /// Report the user's intent. The backend decides what happens and sends
    /// back a set_playback message; the UI never changes its own state here.
    /// </summary>
    private async void OnPlayPause(object sender, RoutedEventArgs e) =>
        await _bridge.SendAsync("toggle_playback");

    /// <summary>
    /// Put the transport button and activity bar into the playing or paused
    /// state. Playing is called out in green; paused stays with the default
    /// foreground so only one state draws attention.
    /// </summary>
    private void SetPlaying(bool playing)
    {
        _playing = playing;

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
