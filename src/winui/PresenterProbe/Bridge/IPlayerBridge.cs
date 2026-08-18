using System;
using System.Threading.Tasks;

namespace PresenterProbe.Bridge;

/// <summary>
/// The boundary between this WinUI frontend and the Python backend.
///
/// Python owns application state and decides what happens; this side renders
/// what it is told and reports what the user pressed. Nothing in
/// <c>Windowing/</c> or <c>Views/</c> should know how that conversation is
/// transported.
///
/// Not implemented yet - this interface exists to fix the shape of the
/// boundary. The planned transport is newline-delimited JSON over a named pipe.
/// </summary>
public interface IPlayerBridge : IDisposable
{
    /// <summary>Raised when the backend sends state for the UI to render.</summary>
    event Action<PlayerMessage>? MessageReceived;

    /// <summary>Raised when the connection to the backend comes and goes.</summary>
    event Action<bool>? ConnectionChanged;

    /// <summary>Begin connecting, retrying until disposed.</summary>
    Task RunAsync();

    /// <summary>Report a user intent - play, pause, stop, read.</summary>
    Task SendAsync(string intent);
}
