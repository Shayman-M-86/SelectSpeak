from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import IntFlag
from queue import Empty
from typing import Protocol, cast

import pythoncom
import win32com.client

from ...config import SpeechConfig
from ...logging_setup import log_event, log_exception, text_preview
from ..contracts import WordCallback
from ..playback import PlaybackCommand, PlaybackController, SpeechRequest
from ..segments import SpeechSegment, split_speech_segments

logger = logging.getLogger(__name__)

SAPI_POLL_INTERVAL_SECONDS = 0.01


class SpeakFlags(IntFlag):
    ASYNC = 1
    PURGE_BEFORE_SPEAK = 2


class SapiToken(Protocol):
    def GetDescription(self) -> str: ...


class SapiTokens(Protocol):
    Count: int

    def Item(self, index: int) -> SapiToken: ...


class SapiStatus(Protocol):
    RunningState: int
    InputWordPosition: int
    InputWordLength: int


class SapiVoice(Protocol):
    Voice: SapiToken
    Rate: int
    Volume: int
    Status: SapiStatus

    def GetVoices(self) -> SapiTokens: ...

    def Speak(self, text: str, flags: int) -> None: ...

    def Pause(self) -> None: ...

    def Resume(self) -> None: ...


@dataclass(slots=True)
class WordTracker:
    offset: int
    last_position: int = -1

    def read(self, status: SapiStatus) -> tuple[int, int] | None:
        position = status.InputWordPosition
        length = status.InputWordLength
        if length <= 0 or position == self.last_position:
            return None
        self.last_position = position
        return self.offset + position, length


class SapiWorker:
    """Own COM and translate generic playback state into SAPI operations."""

    def __init__(
        self,
        config: SpeechConfig,
        playback: PlaybackController,
        word_callback: WordCallback | None,
    ) -> None:
        self._config = config
        self._playback = playback
        self._word_callback = word_callback
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SapiSpeaker"
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        log_event(logger, logging.DEBUG, "speaker.com_initializing")
        pythoncom.CoInitialize()
        try:
            voice = self._create_voice()
            while True:
                try:
                    request = self._playback.next_request(timeout=0.1)
                except Empty:
                    continue
                if self._playback.is_current(request.generation):
                    self._play_request(voice, request)
        except Exception:
            log_exception(logger, "speaker.worker.failed")
            self._playback.fail()
        finally:
            pythoncom.CoUninitialize()
            log_event(logger, logging.INFO, "speaker.com_uninitialized")

    def _create_voice(self) -> SapiVoice:
        voice = cast(SapiVoice, win32com.client.Dispatch("SAPI.SpVoice"))
        self._configure_voice(voice)
        return voice

    def _configure_voice(self, voice: SapiVoice) -> None:
        tokens = voice.GetVoices()
        preferred = self._config.preferred_voice_match.lower()
        for index in range(tokens.Count):
            token = tokens.Item(index)
            if preferred in token.GetDescription().lower():
                voice.Voice = token
                break
        voice.Rate = self._config.speech_rate
        voice.Volume = self._config.speech_volume
        log_event(
            logger,
            logging.INFO,
            "speaker.voice.configured",
            voice=voice.Voice.GetDescription(),
            rate=voice.Rate,
            volume=voice.Volume,
            available_voice_count=tokens.Count,
        )

    def _play_request(self, voice: SapiVoice, request: SpeechRequest) -> None:
        if not self._playback.begin(request.generation):
            return
        log_event(
            logger,
            logging.INFO,
            "speaker.request.started",
            generation=request.generation,
            text_length=len(request.text),
            text_preview=text_preview(request.text),
        )
        try:
            segments = split_speech_segments(request.text)
            for index, segment in enumerate(segments):
                if not self._play_segment(voice, request, segment):
                    return
                if (
                    index < len(segments) - 1
                    and segment.pause_after
                    and not self._wait_for_structure_pause(request.generation)
                ):
                    return
        except Exception:
            log_exception(
                logger, "speaker.request.failed", generation=request.generation
            )
        finally:
            self._playback.complete(request.generation)
            log_event(
                logger,
                logging.INFO,
                "speaker.request.finished",
                generation=request.generation,
                current_generation=self._playback.generation,
                completed_generation=self._playback.completed_generation,
            )

    def _play_segment(
        self,
        voice: SapiVoice,
        request: SpeechRequest,
        segment: SpeechSegment,
    ) -> bool:
        voice.Speak(segment.text, int(SpeakFlags.ASYNC))
        tracker = WordTracker(segment.offset)
        while voice.Status.RunningState != 1:
            if not self._playback.is_current(request.generation):
                self._cancel_voice(voice)
                return False
            self._apply_controls(voice)
            if not self._playback.paused:
                self._report_word(voice.Status, request, tracker)
            time.sleep(SAPI_POLL_INTERVAL_SECONDS)
        return True

    def _apply_controls(self, voice: SapiVoice | None = None) -> None:
        command = self._playback.consume_command()
        if command is PlaybackCommand.PAUSE and voice is not None:
            voice.Pause()
        elif command is PlaybackCommand.RESUME and voice is not None:
            voice.Resume()

    def _report_word(
        self,
        status: SapiStatus,
        request: SpeechRequest,
        tracker: WordTracker,
    ) -> None:
        if self._word_callback is None:
            return
        boundary = tracker.read(status)
        if boundary is not None:
            self._word_callback(request.text, *boundary)

    def _cancel_voice(self, voice: SapiVoice) -> None:
        if self._playback.paused:
            voice.Resume()
        voice.Speak(
            "",
            int(SpeakFlags.ASYNC | SpeakFlags.PURGE_BEFORE_SPEAK),
        )

    def _wait_for_structure_pause(self, generation: int) -> bool:
        remaining = self._config.structure_pause_seconds
        last_tick = time.monotonic()
        while remaining > 0:
            if not self._playback.is_current(generation):
                return False
            self._apply_controls()
            now = time.monotonic()
            if not self._playback.paused:
                remaining -= now - last_tick
            last_tick = now
            time.sleep(min(SAPI_POLL_INTERVAL_SECONDS, max(0.0, remaining)))
        return True


class SapiSpeaker:
    """Thread-safe facade for the Windows SAPI backend."""

    def __init__(
        self, config: SpeechConfig, word_callback: WordCallback | None = None
    ) -> None:
        self._config = config
        self._playback = PlaybackController()
        self._worker = SapiWorker(config, self._playback, word_callback)
        self._worker.start()
        log_event(
            logger,
            logging.INFO,
            "speaker.worker.started",
            preferred_voice=config.preferred_voice_match,
            rate=config.speech_rate,
            volume=config.speech_volume,
            structure_pause_seconds=config.structure_pause_seconds,
        )

    @property
    def active(self) -> bool:
        return self._playback.active

    @property
    def paused(self) -> bool:
        return self._playback.paused

    def speak(self, text: str) -> int | None:
        if len(text) < self._config.minimum_text_length:
            return None
        request, _was_active = self._playback.submit(text)
        log_event(
            logger,
            logging.INFO,
            "speaker.request.queued",
            generation=request.generation,
            text_length=len(text),
        )
        return request.generation

    def stop(self) -> None:
        generation, _was_active = self._playback.cancel()
        log_event(logger, logging.INFO, "speaker.stop.signalled", generation=generation)

    def pause(self) -> None:
        self._playback.request_pause()

    def resume(self) -> None:
        self._playback.request_resume()

    def wait_until_done(self, generation: int) -> bool:
        return self._playback.wait_until_done(generation)
