using Microsoft.UI.Xaml;
using SelectSpeak.UI.Bridge;
using SelectSpeak.UI.Views;

namespace SelectSpeak.UI;

/// <summary>
/// Application startup. The bridge is owned here because its lifetime matches
/// the application rather than any one window.
/// </summary>
public partial class App : Application
{
    private NamedPipePlayerBridge? _bridge;
    private PlayerWindow? _window;

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _bridge = new NamedPipePlayerBridge();
        _window = new PlayerWindow(_bridge);
        _window.Activate();

        // Reconnects on its own, so starting before the backend is fine.
        _ = _bridge.RunAsync();
    }
}
