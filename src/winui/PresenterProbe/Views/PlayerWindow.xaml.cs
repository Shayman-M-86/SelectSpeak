using Microsoft.UI.Xaml;
using PresenterProbe.Bridge;
using PresenterProbe.Windowing;

namespace PresenterProbe.Views;

/// <summary>
/// The player window. It owns what appears inside the window; how the window
/// behaves is delegated to <see cref="WindowController"/>.
/// </summary>
public sealed partial class PlayerWindow : Window
{
    private readonly WindowController _controller;

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
                SetActivity(message.Speaking && !message.Paused);
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
    /// Show the indeterminate activity bar while audio is playing.
    /// </summary>
    private void SetActivity(bool active) => ActivityBar.IsIndeterminate = active;
}
