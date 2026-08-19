using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;

namespace SelectSpeak.UI.Input;

/// <summary>
/// Records a keyboard shortcut, swallowing every keystroke while it runs.
///
/// A low-level keyboard hook sees keys before the focused application does, and
/// returning a non-zero result stops them travelling any further - so a
/// shortcut can use combinations Windows or another application would
/// otherwise claim. That is why this cannot be done from ordinary key events.
///
/// The hook lives in this process, beside the dialog it updates. The backend
/// hears about the result once, when the user confirms it.
/// </summary>
public sealed class ShortcutRecorder : IDisposable
{
    private const int WhKeyboardLowLevel = 13;
    private const int HcAction = 0;
    private const int WmKeyDown = 0x0100;
    private const int WmKeyUp = 0x0101;
    private const int WmSysKeyDown = 0x0104;
    private const int WmSysKeyUp = 0x0105;

    private const int VkEscape = 0x1B;

    // Held so the delegate is not collected while the hook holds a pointer.
    private readonly LowLevelKeyboardProc _proc;

    private IntPtr _hook = IntPtr.Zero;
    private readonly HashSet<string> _modifiers = [];
    private string? _trigger;

    /// <summary>The shortcut so far, in the backend's format, or empty.</summary>
    public event Action<string>? Preview;

    /// <summary>A complete shortcut was pressed. Recording continues.</summary>
    public event Action<string>? Recorded;

    /// <summary>Escape was pressed.</summary>
    public event Action? Cancelled;

    public ShortcutRecorder() => _proc = HookProc;

    public bool IsRecording => _hook != IntPtr.Zero;

    /// <summary>Start intercepting the keyboard. Returns false if it could not.</summary>
    public bool Start()
    {
        if (_hook != IntPtr.Zero)
        {
            return true;
        }

        _modifiers.Clear();
        _trigger = null;

        // A low-level hook needs no module handle of its own, but passing the
        // executable's keeps Windows happy on every supported version.
        var module = GetModuleHandle(null);
        _hook = SetWindowsHookEx(WhKeyboardLowLevel, _proc, module, 0);
        return _hook != IntPtr.Zero;
    }

    /// <summary>Stop intercepting. Safe to call when not recording.</summary>
    public void Stop()
    {
        if (_hook == IntPtr.Zero)
        {
            return;
        }

        UnhookWindowsHookEx(_hook);
        _hook = IntPtr.Zero;
        _modifiers.Clear();
        _trigger = null;
    }

    public void Dispose() => Stop();

    private IntPtr HookProc(int code, IntPtr wParam, IntPtr lParam)
    {
        if (code != HcAction)
        {
            return CallNextHookEx(IntPtr.Zero, code, wParam, lParam);
        }

        var message = (int)wParam;
        var pressed = message is WmKeyDown or WmSysKeyDown;
        var released = message is WmKeyUp or WmSysKeyUp;
        if (!pressed && !released)
        {
            return SwallowKey;
        }

        var info = Marshal.PtrToStructure<KeyboardLowLevelHookStruct>(lParam);
        var virtualKey = (int)info.VirtualKey;

        if (pressed && virtualKey == VkEscape)
        {
            Cancelled?.Invoke();
            return SwallowKey;
        }

        var modifier = ModifierName(virtualKey);
        if (modifier is not null)
        {
            if (pressed)
            {
                // A new modifier after a completed shortcut starts a fresh one.
                if (_trigger is not null)
                {
                    _trigger = null;
                    _modifiers.Clear();
                }
                _modifiers.Add(modifier);
            }
            else
            {
                _modifiers.Remove(modifier);
            }

            if (_trigger is null)
            {
                Preview?.Invoke(Combo(null));
            }
            return SwallowKey;
        }

        if (!pressed)
        {
            return SwallowKey; // Trigger key released; nothing to report.
        }

        var trigger = TriggerName(virtualKey);
        if (trigger is null)
        {
            // Not usable as a shortcut key, so it is swallowed and ignored
            // rather than being reported as a shortcut.
            return SwallowKey;
        }

        if (_modifiers.Count == 0)
        {
            // Without a modifier the shortcut would fire while typing anywhere.
            Preview?.Invoke(string.Empty);
            return SwallowKey;
        }

        _trigger = trigger;
        Recorded?.Invoke(Combo(trigger));
        return SwallowKey;
    }

    // Any non-zero result stops the key reaching the foreground application,
    // which is what makes the recording global.
    private static IntPtr SwallowKey => new(1);

    /// <summary>Build the shortcut in the order keymap.py writes them.</summary>
    private string Combo(string? trigger)
    {
        var ordered = ModifierOrder.Where(_modifiers.Contains);
        var parts = trigger is null ? ordered : ordered.Append(trigger);
        return string.Join("+", parts);
    }

    private static readonly string[] ModifierOrder = ["ctrl", "alt", "shift", "windows"];

    private static string? ModifierName(int virtualKey) => virtualKey switch
    {
        0x11 or 0xA2 or 0xA3 => "ctrl",
        0x12 or 0xA4 or 0xA5 => "alt",
        0x10 or 0xA0 or 0xA1 => "shift",
        0x5B or 0x5C => "windows",
        _ => null,
    };

    /// <summary>The trigger key's backend name, or null if it cannot be one.</summary>
    private static string? TriggerName(int virtualKey)
    {
        if (NamedKeys.TryGetValue(virtualKey, out var named))
        {
            return named;
        }

        // F1-F24 are 0x70-0x87.
        if (virtualKey >= 0x70 && virtualKey <= 0x87)
        {
            return "f" + (virtualKey - 0x70 + 1);
        }

        if ((virtualKey >= 'A' && virtualKey <= 'Z') || (virtualKey >= '0' && virtualKey <= '9'))
        {
            return char.ToLowerInvariant((char)virtualKey).ToString();
        }

        return null;
    }

    // The names keymap.py accepts; anything else it would refuse to bind.
    private static readonly Dictionary<int, string> NamedKeys = new()
    {
        [0x08] = "backspace",
        [0x09] = "tab",
        [0x0D] = "enter",
        [0x20] = "space",
        [0x21] = "page_up",
        [0x22] = "page_down",
        [0x23] = "end",
        [0x24] = "home",
        [0x25] = "left",
        [0x26] = "up",
        [0x27] = "right",
        [0x28] = "down",
        [0x2D] = "insert",
        [0x2E] = "delete",
    };

    private delegate IntPtr LowLevelKeyboardProc(int code, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct KeyboardLowLevelHookStruct
    {
        public uint VirtualKey;
        public uint ScanCode;
        public uint Flags;
        public uint Time;
        public IntPtr ExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(
        int idHook, LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int code, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandle(string? lpModuleName);
}
