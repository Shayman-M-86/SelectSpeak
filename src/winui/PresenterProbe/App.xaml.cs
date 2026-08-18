using Microsoft.UI.Xaml;
using PresenterProbe.Views;

namespace PresenterProbe;

/// <summary>Application startup: create and show the player window.</summary>
public partial class App : Application
{
    private Window? _window;

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new PlayerWindow();
        _window.Activate();
    }
}
