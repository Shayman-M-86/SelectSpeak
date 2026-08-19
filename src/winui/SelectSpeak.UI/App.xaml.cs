using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using SelectSpeak.UI.Bridge;
using SelectSpeak.UI.Views;

namespace SelectSpeak.UI;

/// <summary>
/// Application startup. The bridge is owned here because its lifetime matches
/// the application rather than any one window, and because both windows read
/// from it.
/// </summary>
public partial class App : Application
{
    private NamedPipePlayerBridge? _bridge;
    private PlayerWindow? _window;
    private SettingsWindow? _settings;
    private DispatcherQueue? _dispatcher;

    // Whether the player was on screen when settings opened. Closing settings
    // brings it back only if it was, so opening settings from the tray with no
    // player showing does not make one appear.
    private bool _restorePlayer;

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _bridge = new NamedPipePlayerBridge();

        _window = new PlayerWindow(_bridge);
        _window.Activate();

        // Built and realised now, then hidden. A window shown for the first
        // time paints its default background before Mica is applied, which
        // appears as a white flash; getting that first paint out of the way at
        // startup means opening settings later is instant and clean.
        _settings = new SettingsWindow(_bridge);
        _settings.Dismissed += OnSettingsDismissed;
        _settings.Prepare();

        _dispatcher = DispatcherQueue.GetForCurrentThread();
        _bridge.MessageReceived += OnMessage;

        // Reconnects on its own, so starting before the backend is fine.
        _ = _bridge.RunAsync();
    }

    /// <summary>
    /// Route the messages the settings window owns.
    ///
    /// The player subscribes separately for its own; this handles only what
    /// belongs to settings, so neither window has to filter the other's traffic.
    /// </summary>
    private void OnMessage(PlayerMessage message)
    {
        if (message.Type is not ("show_settings" or "set_settings" or "voice_error"))
        {
            return; // Belongs to the player, which subscribes separately.
        }

        // Pipe messages arrive on a background thread.
        _dispatcher?.TryEnqueue(() =>
        {
            if (message.Type == "show_settings")
            {
                // Whether the player comes back is decided here, not when the
                // window closes: only a player that was on screen is restored.
                _restorePlayer = _window is not null && !_window.IsHidden;

                // Settings is shown before the player is hidden, so there is
                // never a moment with neither window on screen.
                _settings?.Apply(message);
                _settings?.ShowWindow();
                if (_restorePlayer)
                {
                    _window?.ToggleAsHotkey();
                }
                return;
            }

            // set_settings only updates a window that already exists; there is
            // nothing to render into until the user opens it.
            _settings?.Apply(message);
        });
    }

    /// <summary>
    /// Put the player back when settings closes, if it was showing before.
    /// </summary>
    private void OnSettingsDismissed()
    {
        if (!_restorePlayer)
        {
            return;
        }

        _restorePlayer = false;
        // Only toggle if it is actually still hidden: the user may have
        // pressed Alt+A themselves while settings was open, and toggling then
        // would hide the player they just asked for.
        if (_window is not null && _window.IsHidden)
        {
            _window.ToggleAsHotkey();
        }
    }
}
