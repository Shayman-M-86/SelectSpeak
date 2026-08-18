namespace PresenterProbe.Bridge;

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
public readonly record struct PlayerMessage(
    string Type,
    string? Text = null,
    int Position = 0,
    int Length = 0,
    bool Speaking = false,
    bool Paused = false);
