from selectspeak.speech.debug import SpeechDebugEvent, with_queue_delay


def test_playing_event_preserves_metrics_and_adds_queue_delay() -> None:
    ready = SpeechDebugEvent(
        kind="chunk_ready",
        backend="supertonic",
        chunk_index=2,
        text_offset=40,
        text_length=80,
        predicted_synthesis_ms=500,
        actual_synthesis_ms=620,
        audio_ms=3000,
    )

    playing = with_queue_delay(ready, generated_at=10.0, played_at=11.25)

    assert playing.kind == "chunk_playing"
    assert playing.queue_delay_ms == 1250
    assert playing.chunk_index == 2
    assert playing.actual_synthesis_ms == 620
