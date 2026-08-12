from selectspeak.speech.debug import SpeechDebugEvent
from selectspeak.ui.debug_panel import SpeechDebugPanelModel


def test_debug_panel_tracks_chunks_and_formats_active_metrics() -> None:
    model = SpeechDebugPanelModel()
    event = SpeechDebugEvent(
        kind="chunk_playing",
        backend="natural",
        chunk_index=0,
        text_offset=0,
        text_length=12,
        target_characters=20,
    )

    displayed = model.update(event)
    text, is_underrun = model.metrics(displayed)

    assert model.active == event
    assert "PLAY chunk=1" in text
    assert not is_underrun
