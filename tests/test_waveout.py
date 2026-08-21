import threading
import time

from selectspeak.speech.waveout import WaveOutPlayer, _PlaybackTelemetry


def test_playback_telemetry_resets_all_per_playback_measurements() -> None:
    telemetry = _PlaybackTelemetry(
        feed_sizes=[120, 240],
        max_pending_bytes=360,
        loop_iterations=7,
        position_queries=6,
        blocks_submitted=2,
        boundary_delays_ms=[0.2],
        underruns=1,
        stop_reset_ms=3.5,
    )

    telemetry.reset(process_time=12.5, thread_count=4)

    assert telemetry.feed_sizes == []
    assert telemetry.max_pending_bytes == 0
    assert telemetry.loop_iterations == 0
    assert telemetry.position_queries == 0
    assert telemetry.blocks_submitted == 0
    assert telemetry.boundary_delays_ms == []
    assert telemetry.underruns == 0
    assert telemetry.stop_reset_ms is None
    assert telemetry.started_process_time == 12.5
    assert telemetry.started_thread_count == 4
    assert telemetry.peak_thread_count == 4


def test_playback_telemetry_reports_nearest_rank_distribution() -> None:
    assert _PlaybackTelemetry.distribution([]) == (0.0, 0.0, 0.0, 0.0)
    assert _PlaybackTelemetry.distribution([40, 10, 20, 30]) == (10.0, 25.0, 40.0, 40.0)


def test_run_coordinates_playback_steps_and_always_cleans_up(monkeypatch) -> None:
    player = object.__new__(WaveOutPlayer)
    player._stopped = threading.Event()
    player._telemetry = _PlaybackTelemetry()
    player._telemetry.reset(process_time=time.process_time(), thread_count=threading.active_count())
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


def test_feed_records_callback_sizes_and_peak_pending_bytes() -> None:
    player = object.__new__(WaveOutPlayer)
    player._stopped = threading.Event()
    player._audio_condition = threading.Condition()
    player._pending_audio = bytearray()
    player._fed_bytes = 0
    player._telemetry = _PlaybackTelemetry()
    player._telemetry.reset(process_time=time.process_time(), thread_count=threading.active_count())

    player.feed(b"1234")
    player.feed(b"567890")

    assert player._telemetry.feed_sizes == [4, 6]
    assert player._telemetry.max_pending_bytes == 10
    assert player.fed_bytes == 10
