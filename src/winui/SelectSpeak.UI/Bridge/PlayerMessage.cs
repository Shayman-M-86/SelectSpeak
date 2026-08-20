using System.Collections.Generic;

namespace SelectSpeak.UI.Bridge;

/// <summary>
/// One message from the Python backend.
///
/// Kept deliberately small: the backend sends state, never instructions about
/// how to draw it. Character offsets index the same string that is spoken, so
/// highlighting stays aligned with the speech pipeline.
/// </summary>
/// <param name="Type">
/// What the message carries - for example <c>set_text</c>,
/// <c>highlight_word</c>, <c>set_playback</c>, <c>show</c>, <c>hide</c>.
/// </param>
/// <param name="Text">Reader contents or status text, when the type carries one.</param>
/// <param name="Position">Character offset of the spoken word.</param>
/// <param name="Length">Length in characters of the spoken word.</param>
/// <param name="Speaking">Whether playback is active.</param>
/// <param name="Paused">Whether active playback is paused.</param>
/// <param name="AutoHide">Settings: hide the player once reading finishes.</param>
/// <param name="ClipboardMode">Settings: read the clipboard rather than the selection.</param>
/// <param name="DebugEnabled">Settings: speech diagnostics are collected.</param>
/// <param name="Hotkey">Settings: the shortcut that starts a read.</param>
/// <param name="OcrHotkey">Settings: the shortcut that captures text on screen.</param>
/// <param name="Voice">Settings: label of the voice currently in use.</param>
/// <param name="VoiceKey">Settings: key of the voice currently in use.</param>
/// <param name="Voices">Settings: every voice that can be chosen.</param>
public readonly record struct PlayerMessage(
    string Type,
    string? Text = null,
    int Position = 0,
    int Length = 0,
    bool Speaking = false,
    bool Paused = false,
    bool? AutoHide = null,
    bool? ClipboardMode = null,
    bool? DebugEnabled = null,
    string? Hotkey = null,
    string? OcrHotkey = null,
    string? Voice = null,
    string? VoiceKey = null,
    IReadOnlyList<VoiceChoice>? Voices = null);

/// <summary>
/// One selectable voice.
/// </summary>
/// <param name="Key">What to send back when it is chosen.</param>
/// <param name="Label">Its full name, as shown in the list.</param>
/// <param name="Group">The heading it belongs under, such as the engine.</param>
public readonly record struct VoiceChoice(string Key, string Label, string Group);
