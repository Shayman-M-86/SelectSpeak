using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PresenterProbe.Bridge;
using PresenterProbe.Windowing;

namespace PresenterProbe.Views;

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

    private readonly WindowController _controller;
    private bool _playing;

    public PlayerWindow()
    {
        this.InitializeComponent();

        Title = "SelectSpeak";

        // Draw into the caption area so the title row above is the title bar.
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);

        _controller = new WindowController(this);

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
    /// Toggle playback locally.
    ///
    /// Once the bridge is connected this should send an intent and let the
    /// backend report the new state back, rather than deciding it here.
    /// </summary>
    private void OnPlayPause(object sender, RoutedEventArgs e) => SetPlaying(!_playing);

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

        ActivityBar.IsIndeterminate = playing;
    }
}
