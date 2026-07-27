import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Protocol, cast

import pythoncom
import win32com.client

from .config import AppConfig
from .logging_setup import log_event, log_exception, text_preview

logger = logging.getLogger(__name__)

WordCallback = Callable[[str, int, int], None]


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


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    generation: int
    text: str


class SapiSpeaker:
    """Own SAPI on one COM thread and expose thread-safe playback controls."""

    def __init__(
        self, config: AppConfig, word_callback: WordCallback | None = None
    ) -> None:
        self._config = config
        self._word_callback = word_callback
        self._queue: Queue[SpeechRequest] = Queue()
        self._condition = threading.Condition()
        self._generation = 0
        self._active_generation: int | None = None
        self._completed_generation = 0
        self._paused = False
        self._pause_requested = threading.Event()
        self._resume_requested = threading.Event()
        self._failed = False
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SapiSpeaker"
        )
        self._thread.start()
        log_event(
            logger,
            logging.INFO,
            "speaker.worker.started",
            preferred_voice=config.preferred_voice_match,
            rate=config.speech_rate,
            volume=config.speech_volume,
        )

    @property
    def active(self) -> bool:
        with self._condition:
            return self._active_generation is not None

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def speak(self, text: str) -> int | None:
        log_event(
            logger,
            logging.DEBUG,
            "speaker.speak.requested",
            text_length=len(text),
            text_preview=text_preview(text),
        )
        if len(text) < self._config.minimum_text_length:
            log_event(
                logger,
                logging.WARNING,
                "speaker.speak.rejected_short_text",
                text_length=len(text),
                minimum_length=self._config.minimum_text_length,
            )
            return None
        with self._condition:
            if self._failed:
                raise RuntimeError("The SAPI speech worker failed to start")
            self._generation += 1
            request = SpeechRequest(self._generation, text)
            self._drain_queue()
            self._pause_requested.clear()
            self._queue.put(request)
            self._resume_requested.set()
            self._condition.notify_all()
            log_event(
                logger,
                logging.INFO,
                "speaker.request.queued",
                generation=request.generation,
                text_length=len(text),
            )
            return request.generation

    def stop(self) -> None:
        log_event(logger, logging.INFO, "speaker.stop.requested")
        with self._condition:
            self._generation += 1
            generation = self._generation
            self._drain_queue()
            self._pause_requested.clear()
            self._resume_requested.set()
            self._condition.notify_all()
        log_event(
            logger,
            logging.INFO,
            "speaker.stop.signalled",
            generation=generation,
        )

    def pause(self) -> None:
        log_event(logger, logging.DEBUG, "speaker.pause.requested")
        with self._condition:
            if self._active_generation is not None and not self._paused:
                self._pause_requested.set()
                log_event(
                    logger,
                    logging.INFO,
                    "speaker.pause.signalled",
                    generation=self._active_generation,
                )
            else:
                log_event(
                    logger,
                    logging.DEBUG,
                    "speaker.pause.ignored",
                    active_generation=self._active_generation,
                    paused=self._paused,
                )

    def resume(self) -> None:
        log_event(logger, logging.DEBUG, "speaker.resume.requested")
        with self._condition:
            if self._paused:
                self._resume_requested.set()
                log_event(
                    logger,
                    logging.INFO,
                    "speaker.resume.signalled",
                    generation=self._active_generation,
                )
            else:
                log_event(logger, logging.DEBUG, "speaker.resume.ignored_not_paused")

    def wait_until_done(self, generation: int) -> bool:
        """Wait for completion; return False when a newer request supersedes it."""
        log_event(
            logger,
            logging.DEBUG,
            "speaker.wait.started",
            generation=generation,
        )
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    self._failed
                    or self._generation != generation
                    or self._completed_generation >= generation
                )
            )
            completed = (
                not self._failed
                and self._generation == generation
                and self._completed_generation >= generation
            )
        log_event(
            logger,
            logging.DEBUG,
            "speaker.wait.completed",
            generation=generation,
            completed=completed,
        )
        return completed

    def _run(self) -> None:
        log_event(logger, logging.DEBUG, "speaker.com_initializing")
        pythoncom.CoInitialize()
        try:
            voice = cast(SapiVoice, win32com.client.Dispatch("SAPI.SpVoice"))
            log_event(logger, logging.DEBUG, "speaker.sapi_dispatched")
            self._configure_voice(voice)
            while True:
                try:
                    request = self._queue.get(timeout=0.1)
                except Empty:
                    continue
                if self._is_superseded(request.generation):
                    log_event(
                        logger,
                        logging.DEBUG,
                        "speaker.request.skipped_superseded",
                        generation=request.generation,
                    )
                    continue
                self._speak_request(voice, request)
        except Exception:
            log_exception(logger, "speaker.worker.failed")
            with self._condition:
                self._failed = True
                self._condition.notify_all()
        finally:
            pythoncom.CoUninitialize()
            log_event(logger, logging.INFO, "speaker.com_uninitialized")

    def _configure_voice(self, voice: SapiVoice) -> None:
        tokens = voice.GetVoices()
        preferred = self._config.preferred_voice_match.lower()
        for index in range(tokens.Count):
            token = tokens.Item(index)
            if preferred in token.GetDescription().lower():
                voice.Voice = token
                log_event(
                    logger,
                    logging.DEBUG,
                    "speaker.preferred_voice.matched",
                    voice=token.GetDescription(),
                    index=index,
                )
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

    def _speak_request(self, voice: SapiVoice, request: SpeechRequest) -> None:
        async_flag = 1
        purge_before_speak = 2
        with self._condition:
            self._active_generation = request.generation
            self._paused = False

        log_event(
            logger,
            logging.INFO,
            "speaker.request.started",
            generation=request.generation,
            text_length=len(request.text),
            text_preview=text_preview(request.text),
        )
        try:
            voice.Speak(request.text, async_flag)
            log_event(
                logger,
                logging.DEBUG,
                "speaker.sapi_speak.called",
                generation=request.generation,
            )
            time.sleep(0.1)
            last_word_position = -1
            while voice.Status.RunningState != 1:
                if self._is_superseded(request.generation):
                    log_event(
                        logger,
                        logging.INFO,
                        "speaker.request.superseded",
                        generation=request.generation,
                    )
                    if self.paused:
                        voice.Resume()
                    voice.Speak("", async_flag | purge_before_speak)
                    return
                if self._pause_requested.is_set():
                    self._pause_requested.clear()
                    voice.Pause()
                    with self._condition:
                        self._paused = True
                    log_event(
                        logger,
                        logging.INFO,
                        "speaker.sapi_paused",
                        generation=request.generation,
                    )
                if self._resume_requested.is_set():
                    self._resume_requested.clear()
                    if self.paused:
                        voice.Resume()
                        with self._condition:
                            self._paused = False
                        log_event(
                            logger,
                            logging.INFO,
                            "speaker.sapi_resumed",
                            generation=request.generation,
                        )
                if not self.paused and self._word_callback:
                    position = voice.Status.InputWordPosition
                    length = voice.Status.InputWordLength
                    if length > 0 and position != last_word_position:
                        last_word_position = position
                        log_event(
                            logger,
                            logging.DEBUG,
                            "speaker.word_observed",
                            generation=request.generation,
                            position=position,
                            length=length,
                        )
                        self._word_callback(request.text, position, length)
                time.sleep(0.05)
        except Exception:
            log_exception(
                logger,
                "speaker.request.failed",
                generation=request.generation,
            )
        finally:
            with self._condition:
                if self._active_generation == request.generation:
                    self._active_generation = None
                    self._paused = False
                if self._generation == request.generation:
                    self._completed_generation = request.generation
                self._condition.notify_all()
            log_event(
                logger,
                logging.INFO,
                "speaker.request.finished",
                generation=request.generation,
                current_generation=self._generation,
                completed_generation=self._completed_generation,
            )

    def _is_superseded(self, generation: int) -> bool:
        with self._condition:
            return self._generation != generation

    def _drain_queue(self) -> None:
        drained = 0
        while True:
            try:
                self._queue.get_nowait()
                drained += 1
            except Empty:
                if drained:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "speaker.queue.drained",
                        request_count=drained,
                    )
                return
