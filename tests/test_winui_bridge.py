import json
import types

from selectspeak.app.application import SelectSpeakApp
from selectspeak.ui.hints import idle_hint, shortcut_label
from selectspeak.ui.winui_bridge import WinUiPlayer


class _Session:
    """Stand in for PlaybackSession, which owns the real playback state."""

    def __init__(self, *, speaking: bool, paused: bool) -> None:
        self._snapshot = types.SimpleNamespace(speaking=speaking, paused=paused)

    def snapshot(self) -> types.SimpleNamespace:
        return self._snapshot


def _app_with(*, speaking: bool, paused: bool) -> tuple[SelectSpeakApp, list[str]]:
    app = SelectSpeakApp()
    app._session = _Session(speaking=speaking, paused=paused)
    calls: list[str] = []
    app.pause = lambda: calls.append("pause")
    app.resume = lambda: calls.append("resume")
    app.replay = lambda: calls.append("replay")
    return app, calls


def test_toggle_pauses_while_speaking() -> None:
    app, calls = _app_with(speaking=True, paused=False)
    app.toggle_playback()
    assert calls == ["pause"]


def test_toggle_resumes_while_paused() -> None:
    app, calls = _app_with(speaking=True, paused=True)
    app.toggle_playback()
    assert calls == ["resume"]


def test_toggle_replays_when_idle() -> None:
    app, calls = _app_with(speaking=False, paused=False)
    app.toggle_playback()
    assert calls == ["replay"]


def _player_recording_sends() -> tuple[WinUiPlayer, list[dict[str, object]]]:
    """A player whose messages are captured instead of written to a pipe."""
    player = WinUiPlayer(hotkey="alt+s", ocr_hotkey="alt+d")
    sent: list[dict[str, object]] = []
    player._send = lambda message_type, **fields: sent.append({"type": message_type, **fields})
    return player, sent


def test_winui_player_routes_the_intents_the_ui_actually_sends() -> None:
    seen: list[str] = []
    player = WinUiPlayer(
        on_toggle_playback=lambda: seen.append("toggle_playback"),
        on_stop=lambda: seen.append("stop"),
        on_settings=lambda: seen.append("settings"),
    )

    for intent in ("toggle_playback", "stop", "settings"):
        player._dispatch({"type": intent})
    player.drain_callbacks()

    assert seen == ["toggle_playback", "stop", "settings"]


def test_unknown_intent_is_ignored() -> None:
    player = WinUiPlayer()
    player._dispatch({"type": "not_a_real_intent"})
    assert player.drain_callbacks() == 0


def test_status_messages_carry_the_same_words_as_the_tk_player() -> None:
    player, sent = _player_recording_sends()

    player.show_idle_hint()

    assert sent == [
        {
            "type": "set_status",
            "text": idle_hint("alt+s", "alt+d", clipboard_mode=False),
        }
    ]


def _last_of_type(sent: list[dict[str, object]], message_type: str) -> dict[str, object]:
    return [message for message in sent if message["type"] == message_type][-1]


def test_clipboard_mode_changes_the_idle_hint() -> None:
    player, sent = _player_recording_sends()

    player.set_clipboard_mode(True)

    status = _last_of_type(sent, "set_status")
    assert status["text"] == idle_hint("alt+s", "alt+d", clipboard_mode=True)


def test_capture_complete_reports_the_new_shortcut() -> None:
    player, sent = _player_recording_sends()

    player.show_capture_complete("ctrl+shift+r")

    assert player._hotkey == "ctrl+shift+r"
    status = _last_of_type(sent, "set_status")
    assert status["text"] == f"Shortcut set to {shortcut_label('ctrl+shift+r')}"


def test_changing_a_setting_pushes_the_whole_set_back() -> None:
    """The window renders what it is sent, so every change re-sends the set."""
    player, sent = _player_recording_sends()

    player.set_auto_hide(False)

    settings = _last_of_type(sent, "set_settings")
    assert settings["auto_hide"] is False
    assert settings["clipboard_mode"] is False
    assert settings["hotkey"] == "Alt+S"
    assert settings["ocr_hotkey"] == "Alt+D"


def test_opening_settings_carries_the_current_values() -> None:
    player, sent = _player_recording_sends()
    player.set_clipboard_mode(True)
    sent.clear()

    player.open_settings()

    assert sent[0]["type"] == "show_settings"
    assert sent[0]["clipboard_mode"] is True


def test_settings_window_intents_are_routed() -> None:
    seen: list[str] = []
    player = WinUiPlayer(
        on_toggle_auto_hide=lambda: seen.append("auto_hide"),
        on_toggle_clipboard=lambda: seen.append("clipboard"),
        on_toggle_debug=lambda: seen.append("debug"),
        on_capture_hotkey=lambda: seen.append("capture_hotkey"),
    )

    for intent in ("toggle_auto_hide", "toggle_clipboard", "toggle_debug", "capture_hotkey"):
        player._dispatch({"type": intent})
    player.drain_callbacks()

    assert seen == ["auto_hide", "clipboard", "debug", "capture_hotkey"]


def test_a_message_serialises_to_exactly_one_line() -> None:
    """The UI splits the stream on newlines, so an embedded newline in the
    payload must survive as an escape rather than ending the message early."""
    payload = {"type": "set_text", "text": "first line\nsecond line"}
    line = json.dumps(payload, ensure_ascii=False) + "\n"

    assert line.count("\n") == 1
    assert line.endswith("\n")
    assert json.loads(line)["text"] == "first line\nsecond line"


def test_send_is_a_no_op_while_disconnected() -> None:
    """Intents are dropped rather than queued, and must not raise."""
    player = WinUiPlayer()
    assert player._pipe is None
    player.set_status("no pipe yet")
