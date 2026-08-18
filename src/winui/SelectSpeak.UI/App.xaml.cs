using System;
using System.Linq;
using Microsoft.UI.Xaml;

namespace SelectSpeak.UI;

public partial class App : Application
{
    private const string DefaultPipeName = "selectspeak-ui";

    private PlayerBridge? _bridge;
    private MainWindow? _window;

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // --pipe <name> lets a second instance talk to a different backend.
        var arguments = Environment.GetCommandLineArgs();
        var pipeName = DefaultPipeName;
        var index = Array.FindIndex(arguments, a => a == "--pipe");
        if (index >= 0 && index + 1 < arguments.Length)
        {
            pipeName = arguments[index + 1];
        }

        _bridge = new PlayerBridge(pipeName);
        _window = new MainWindow(_bridge);
        _window.Activate();

        // Reconnects on its own, so a UI start before the backend is fine.
        _ = _bridge.RunAsync();
    }
}
