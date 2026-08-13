import threading

from selectspeak.speech.waveout import WaveOutPlayer


def test_run_coordinates_playback_steps_and_always_cleans_up(monkeypatch) -> None:
    player = object.__new__(WaveOutPlayer)
    player._stopped = threading.Event()
    calls: list[str] = []

    monkeypatch.setattr(player, "_wait_for_prebuffer", lambda: calls.append("prebuffer"))
    monkeypatch.setattr(player, "_mark_playback_started", lambda: calls.append("started"))
    monkeypatch.setattr(
        player,
        "_process_playback_updates",
        lambda queued: calls.append("updates"),
    )
    monkeypatch.setattr(
        player,
        "_fill_playback_queue",
        lambda queued: calls.append("fill"),
    )
    monkeypatch.setattr(player, "_playback_finished", lambda queued: False)

    def handle_buffer_state(queued, underrun_started_at):
        calls.append("buffer")
        player._stopped.set()
        return 1.25

    def cleanup(queued, underrun_started_at):
        assert not queued
        assert underrun_started_at == 1.25
        calls.append("cleanup")

    monkeypatch.setattr(player, "_handle_buffer_state", handle_buffer_state)
    monkeypatch.setattr(
        player,
        "_finish_playback_events",
        lambda: calls.append("finish_events"),
    )
    monkeypatch.setattr(player, "_cleanup_playback", cleanup)

    player._run()

    assert calls == [
        "prebuffer",
        "started",
        "updates",
        "fill",
        "buffer",
        "finish_events",
        "cleanup",
    ]
