using System;
using System.IO;

namespace PresenterProbe.Windowing;

/// <summary>
/// Writes focus diagnostics to %TEMP%\selectspeak_focus.log.
///
/// "Focused" is not one thing. Three signals decide how the window looks and
/// behaves, and with WS_EX_NOACTIVATE they can disagree:
///
///   foreground  - GetForegroundWindow, the window the user is working in.
///                 This is what paints a title bar active or inactive.
///   active      - GetActiveWindow, active within this thread.
///   focus       - GetFocus, which control receives keystrokes.
///
/// A no-activate window can be clicked and used while never becoming the
/// foreground window, which is why its title bar can look greyed out.
/// </summary>
public static class FocusLog
{
    private static readonly string Path =
        System.IO.Path.Combine(System.IO.Path.GetTempPath(), "selectspeak_focus.log");

    private static readonly object Gate = new();

    public static void Start(IntPtr hwnd)
    {
        lock (Gate)
        {
            File.WriteAllText(
                Path,
                $"{DateTime.Now:HH:mm:ss.fff}  session start, window 0x{hwnd.ToInt64():X}"
                + Environment.NewLine);
        }
    }

    /// <summary>Record a plain note, without querying window state.</summary>
    public static void Note(string line)
    {
        lock (Gate)
        {
            try
            {
                File.AppendAllText(
                    Path, $"{DateTime.Now:HH:mm:ss.fff}  {line}" + Environment.NewLine);
            }
            catch (IOException)
            {
            }
        }
    }

    /// <summary>Record an event alongside the three focus signals.</summary>
    public static void Write(string label, IntPtr hwnd)
    {
        var foreground = Interop.GetForegroundWindow();
        var line =
            $"{DateTime.Now:HH:mm:ss.fff}  {label,-28} "
            + $"foreground={(foreground == hwnd ? "SELF" : $"0x{foreground.ToInt64():X}")} "
            + $"active={(Interop.GetActiveWindow() == hwnd ? "SELF" : "other")} "
            + $"focus=0x{Interop.GetFocus().ToInt64():X}";

        lock (Gate)
        {
            try
            {
                File.AppendAllText(Path, line + Environment.NewLine);
            }
            catch (IOException)
            {
                // Diagnostics must never take the window down.
            }
        }
    }
}
