"""Run the temporary, repeatable Package A audio workload.

This script and the WaveOut counters it consumes are old-path measurement tools.
Package O may remove them after the final comparison is preserved.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from selectspeak.config.settings import SettingsStore
from selectspeak.infrastructure.logging import configure_logging
from selectspeak.speech.contracts import Speaker

COMPLETION_TEXT = (
    "SelectSpeak turns selected text into clear local speech. "
    "This fixed passage measures startup, buffering, highlighting, and clean playback completion."
)
PAUSE_TEXT = (
    "Pause and resume must preserve the current request and continue from the same audio position. "
    "The workload stays deliberately long enough for both controls to occur during playback. "
) * 2
STOP_TEXT = (
    "Stopping speech must silence the device promptly and prevent stale highlighting callbacks. "
) * 8

logger = logging.getLogger("selectspeak.baseline")


def _create_backend(config, backend: str) -> Speaker:
    if backend == "supertonic":
        # Development uses the venv installation directly. The application-level
        # optional-layer fallback is not part of this backend-specific benchmark.
        from selectspeak.speech.backends.supertonic import SupertonicSpeaker

        return SupertonicSpeaker(config.speech)
    from selectspeak.speech.backends.natural import NaturalVoiceSpeaker

    return NaturalVoiceSpeaker(config.speech, None)


def _sample_resources(label: str, duration: float = 1.0) -> None:
    started_at = time.monotonic()
    started_cpu = time.process_time()
    time.sleep(duration)
    elapsed = time.monotonic() - started_at
    cpu = time.process_time() - started_cpu
    logger.info(
        "baseline.resources label=%s elapsed_ms=%s process_cpu_pct=%.2f threads=%s",
        label,
        round(elapsed * 1000),
        cpu / elapsed * 100 if elapsed else 0.0,
        threading.active_count(),
    )


def _playback_start(speaker: Speaker) -> float:
    player = getattr(speaker, "_player", None)
    if player is None:
        raise RuntimeError("Backend does not expose the temporary WaveOut player")
    return float(player._started_at)


def _wait_for_new_audio(speaker: Speaker, previous_start: float) -> None:
    player = getattr(speaker, "_player", None)
    if player is None:
        raise RuntimeError("Backend does not expose the temporary WaveOut player")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if float(player._started_at) != previous_start and player.wait_until_started(timeout=0.05):
            return
        time.sleep(0.01)
    raise RuntimeError("New playback did not start within 30 seconds")


def _speak_to_completion(speaker: Speaker) -> None:
    generation = speaker.speak(COMPLETION_TEXT)
    if generation is None or not speaker.wait_until_done(generation):
        raise RuntimeError("Completion workload did not complete normally")


def _pause_and_resume(speaker: Speaker) -> None:
    previous_start = _playback_start(speaker)
    generation = speaker.speak(PAUSE_TEXT)
    if generation is None:
        raise RuntimeError("Pause workload was rejected")
    _wait_for_new_audio(speaker, previous_start)
    time.sleep(0.35)
    pause_started_at = time.monotonic()
    speaker.pause()
    pause_call_ms = (time.monotonic() - pause_started_at) * 1000
    time.sleep(0.3)
    resume_started_at = time.monotonic()
    speaker.resume()
    resume_call_ms = (time.monotonic() - resume_started_at) * 1000
    if not speaker.wait_until_done(generation):
        raise RuntimeError("Pause/resume workload did not complete normally")
    logger.info(
        "baseline.pause_resume pause_call_ms=%.3f held_ms=300 resume_call_ms=%.3f",
        pause_call_ms,
        resume_call_ms,
    )


def _stop_during_playback(speaker: Speaker) -> None:
    previous_start = _playback_start(speaker)
    generation = speaker.speak(STOP_TEXT)
    if generation is None:
        raise RuntimeError("Stop workload was rejected")
    _wait_for_new_audio(speaker, previous_start)
    time.sleep(0.35)
    stop_started_at = time.monotonic()
    speaker.stop()
    stop_call_ms = (time.monotonic() - stop_started_at) * 1000
    settled = not speaker.wait_until_done(generation)
    logger.info("baseline.stop stop_call_ms=%.3f request_settled=%s", stop_call_ms, settled)


def _best_effort_cleanup(speaker: Speaker) -> None:
    speaker.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("natural", "supertonic"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    output = args.output.resolve()
    config = replace(
        SettingsStore().load(),
        speech_backend=args.backend,
        logging_enabled=True,
        log_file=str(output),
    )
    configure_logging(config.logging)
    logger.info("baseline.workload.started backend=%s", args.backend)
    speaker = _create_backend(config, args.backend)
    try:
        _sample_resources("idle")
        _speak_to_completion(speaker)
        _pause_and_resume(speaker)
        _stop_during_playback(speaker)
        _sample_resources("post_stop")
    finally:
        _best_effort_cleanup(speaker)
    logger.info("baseline.workload.finished backend=%s", args.backend)
    logging.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
