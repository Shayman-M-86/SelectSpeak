"""The contract the application layer holds a renderer to.

Python owns every decision; a renderer draws what it is sent and reports which
button was pressed. That split is what lets the player live in another process
without the application layer knowing.

Declaring it here rather than leaving it implicit means a renderer that has
fallen behind is a type error rather than an ``AttributeError`` at the moment a
user presses the button that needs it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from ..speech.debug import SpeechDebugEvent
from ..speech.voices import VoiceOption


@runtime_checkable
class Player(Protocol):
    """Render playback state and report user intent."""

    # -- lifecycle ---------------------------------------------------------

    def mainloop(self) -> None:
        """Run until the player closes. This owns the process's main thread."""

    def destroy(self) -> None:
        """Tear the player down; the application is shutting down."""

    def call_soon(self, callback: Callable[[], None]) -> None:
        """Queue work onto the player's own thread from any other thread."""

    # -- window ------------------------------------------------------------

    def show(self) -> None: ...

    # -- playback ----------------------------------------------------------

    def set_playback(self, *, speaking: bool, paused: bool = False, text: str = "") -> None:
        """Render the current playback state and the text being read."""

    def highlight_word(self, position: int, length: int) -> None:
        """Mark the spoken word. Offsets index the text that was spoken."""

    # -- speech diagnostics ------------------------------------------------

    def update_speech_debug(self, event: SpeechDebugEvent) -> None: ...

    def reset_speech_debug(self) -> None: ...

    # -- settings ----------------------------------------------------------
    #
    # Python owns and persists each of these, so a setter records the value and
    # the renderer holds no state of its own.

    def set_clipboard_mode(self, enabled: bool) -> None: ...

    def set_auto_hide(self, enabled: bool) -> None: ...

    def set_debug_enabled(self, enabled: bool) -> None: ...

    def set_hotkey(self, hotkey: str) -> None: ...

    def set_ocr_hotkey(self, hotkey: str) -> None: ...

    def open_settings(self) -> None:
        """Show the settings, wherever this renderer keeps them."""

    # -- voices ------------------------------------------------------------

    def set_voice_options(self, options: tuple[VoiceOption, ...], selected_key: str) -> None: ...

    def set_voice_selection(self, key: str, label: str, *, activity: str = "") -> None:
        """Record the chosen voice, whether or not it has finished loading."""

    # -- transient reporting -----------------------------------------------
    #
    # A renderer without anywhere to put one of these may ignore it, but it
    # must accept the call: the application layer reports what happened and
    # does not track which renderer can show what.

    def show_backend_loading(self, activity: str = "loading") -> None: ...

    def show_backend_ready(self, label: str) -> None: ...

    def show_backend_error(self, message: str) -> None: ...

    def show_hotkey_error(self, message: str) -> None: ...

    def show_capture_complete(self, hotkey: str) -> None:
        """A shortcut was bound; render it wherever this renderer names it."""
