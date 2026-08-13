import ctypes
import logging
import os
import tkinter as tk
from collections.abc import Callable
from queue import Empty, SimpleQueue

from ..logging_setup import log_event, log_exception
from ..speech.debug import SpeechDebugEvent
from ..speech.voices import VoiceOption
from .debug_panel import SpeechDebugPanelModel
from .theme import (
    ACCENT,
    BACKGROUND,
    BUTTON_BACKGROUND,
    BUTTON_BORDER,
    CHUNK_COLOURS,
    DIM_FOREGROUND,
    FOREGROUND,
    GREEN,
    MIN_DEBUG_READING_HEIGHT,
    MIN_IDLE_HEIGHT,
    MIN_READING_HEIGHT,
    READER_BACKGROUND,
    RED,
    SPINNER,
    STATUS_WRAP_LENGTH,
    WINDOW_WIDTH,
)

logger = logging.getLogger(__name__)

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_SWP_REFRESH_FRAME_NO_ACTIVATE = 0x0037


class PlayerWindow(tk.Tk):
    def __init__(
        self,
        *,
        app_name: str,
        hotkey: str,
        ocr_hotkey: str = "alt+d",
        on_play: Callable[[], None],
        on_read: Callable[[], None],
        on_pause: Callable[[], None],
        on_resume: Callable[[], None],
        on_stop: Callable[[], None],
        on_select_voice: Callable[[str], None],
        on_toggle_clipboard: Callable[[], None],
        on_toggle_auto_hide: Callable[[], None],
        on_toggle_debug: Callable[[], None],
        on_capture_hotkey: Callable[[], None],
        auto_hide: bool = True,
        speech_backend: str = "windows",
        debug_enabled: bool = False,
    ) -> None:
        super().__init__()
        self._app_name = app_name
        self._hotkey = hotkey
        self._ocr_hotkey = ocr_hotkey
        self._clipboard_mode = False
        self._auto_hide = auto_hide
        self._speech_backend = speech_backend
        self._on_select_voice = on_select_voice
        self._voice_options: tuple[VoiceOption, ...] = ()
        self._selected_voice_key = tk.StringVar(self, "")
        self._debug_enabled = debug_enabled
        self._debug = SpeechDebugPanelModel()
        self._on_play = on_play
        self._on_read = on_read
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_stop = on_stop
        self._animation_job: str | None = None
        self._animation_frame = 0
        self._reader_generation = 0
        self._reader_text = ""
        self._callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._drag_x = 0
        self._drag_y = 0
        self._user_minimized = False

        self.title(app_name)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.configure(bg=BACKGROUND)
        self.resizable(False, False)
        self.update_idletasks()
        self._enable_no_activate()

        self.bind("<ButtonPress-1>", self._begin_drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Map>", self._on_map)

        self._content = tk.Frame(self, bg=BACKGROUND, padx=10, pady=8)
        self._content.pack(fill="both", expand=True)
        self._build_title_row(self._content)
        self._build_status(self._content)
        self._build_reader(self._content)
        self._build_controls(
            self._content,
            on_toggle_clipboard=on_toggle_clipboard,
            on_toggle_auto_hide=on_toggle_auto_hide,
            on_toggle_debug=on_toggle_debug,
            on_capture_hotkey=on_capture_hotkey,
        )
        self.update_idletasks()
        width, height = self._required_size(MIN_IDLE_HEIGHT)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(
            f"{width}x{height}"
            f"+{max(0, screen_width - width - 20)}"
            f"+{max(0, screen_height - height - 60)}"
        )
        self.after(20, self._drain_callbacks)
        self.withdraw()
        log_event(
            logger,
            logging.INFO,
            "player.created",
            app_name=app_name,
            hotkey=hotkey,
            initial_mode="auto",
            auto_hide=auto_hide,
            width=width,
            height=height,
            requested_width=self._content.winfo_reqwidth(),
            requested_height=self._content.winfo_reqheight(),
            scaling=round(float(self.tk.call("tk", "scaling")), 3),
        )

    def call_soon(self, callback: Callable[[], None]) -> None:
        self._callbacks.put(callback)
        log_event(
            logger,
            logging.DEBUG,
            "player.callback.queued",
            callback=getattr(callback, "__name__", type(callback).__name__),
        )

    def show(self) -> None:
        log_event(logger, logging.INFO, "player.show")
        self.deiconify()
        self.lift()

    def hide(self) -> None:
        log_event(logger, logging.INFO, "player.hidden")
        self.withdraw()

    def _enable_no_activate(self) -> None:
        if os.name != "nt":
            log_event(logger, logging.DEBUG, "player.no_activate.unavailable")
            return
        try:
            user32 = ctypes.windll.user32
            client_handle = self.winfo_id()
            window_handle = user32.GetParent(client_handle) or client_handle
            extended_style = user32.GetWindowLongPtrW(
                window_handle,
                _GWL_EXSTYLE,
            )
            ctypes.set_last_error(0)
            previous_style = user32.SetWindowLongPtrW(
                window_handle,
                _GWL_EXSTYLE,
                extended_style | _WS_EX_NOACTIVATE,
            )
            if previous_style == 0 and ctypes.get_last_error() != 0:
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetWindowPos(
                window_handle,
                0,
                0,
                0,
                0,
                _SWP_REFRESH_FRAME_NO_ACTIVATE,
            )
            log_event(
                logger,
                logging.INFO,
                "player.no_activate.enabled",
                window_handle=window_handle,
            )
        except Exception:
            log_exception(logger, "player.no_activate.failed")

    def set_hotkey(self, hotkey: str) -> None:
        log_event(logger, logging.INFO, "player.hotkey.updated", hotkey=hotkey)
        self._hotkey = hotkey
        self._hotkey_button.config(text=hotkey.upper())

    def set_clipboard_mode(self, enabled: bool) -> None:
        log_event(
            logger,
            logging.INFO,
            "player.capture_mode.updated",
            mode="clipboard" if enabled else "auto",
        )
        self._clipboard_mode = enabled
        if enabled:
            self._clipboard_button.config(
                text="Mode: Clipboard",
                fg=ACCENT,
                font=("Segoe UI", 7, "bold"),
            )
        else:
            self._clipboard_button.config(
                text="Mode: Auto",
                fg=DIM_FOREGROUND,
                font=("Segoe UI", 7),
            )
        self.show_idle_hint()

    def set_auto_hide(self, enabled: bool) -> None:
        self._auto_hide = enabled
        self._auto_hide_button.config(
            text=f"Auto hide: {'On' if enabled else 'Off'}",
            fg=ACCENT if enabled else DIM_FOREGROUND,
            font=("Segoe UI", 7, "bold" if enabled else "normal"),
        )
        log_event(
            logger,
            logging.INFO,
            "player.auto_hide.updated",
            enabled=enabled,
        )

    def set_debug_enabled(self, enabled: bool) -> None:
        self._debug_enabled = enabled
        self._debug_button.config(
            text=f"Debug: {'On' if enabled else 'Off'}",
            fg=ACCENT if enabled else DIM_FOREGROUND,
            font=("Segoe UI", 7, "bold" if enabled else "normal"),
        )
        if enabled:
            self._debug_frame.pack(fill="x", pady=(0, 5), before=self._control_row)
            self._render_debug_metrics()
            self._apply_chunk_tags()
        else:
            self._debug_frame.pack_forget()
            self._clear_chunk_tags()
        minimum = (
            MIN_DEBUG_READING_HEIGHT
            if enabled and self._reader_frame.winfo_ismapped()
            else MIN_READING_HEIGHT
            if self._reader_frame.winfo_ismapped()
            else MIN_IDLE_HEIGHT
        )
        self._resize(minimum)
        log_event(logger, logging.INFO, "player.speech_debug.updated", enabled=enabled)

    def update_speech_debug(self, event: SpeechDebugEvent) -> None:
        display_event = self._debug.update(event)
        if not self._debug_enabled:
            return
        self._apply_chunk_tags(
            event if event.kind == "chunk_playing" else None
        )
        self._render_debug_metrics(display_event)

    def reset_speech_debug(self) -> None:
        self._debug.reset()
        self._clear_chunk_tags()
        if self._debug_enabled:
            self._render_debug_metrics()

    def set_voice_options(
        self,
        options: tuple[VoiceOption, ...],
        selected_key: str,
    ) -> None:
        self._voice_options = options
        self._voice_menu.delete(0, "end")
        previous_group = ""
        for option in options:
            if option.group != previous_group:
                if previous_group:
                    self._voice_menu.add_separator()
                self._voice_menu.add_command(label=option.group, state="disabled")
                previous_group = option.group
            self._voice_menu.add_radiobutton(
                label=option.label,
                value=option.key,
                variable=self._selected_voice_key,
                command=lambda key=option.key: self._on_select_voice(key),
            )
        selected = next(
            (option for option in options if option.key == selected_key),
            options[0] if options else None,
        )
        if selected is not None:
            self.set_voice_selection(selected.key, selected.short_label)
        else:
            self._backend_button.config(text="Voice: Unavailable", state="disabled")

    def set_voice_selection(
        self,
        key: str,
        label: str,
        *,
        loading: bool = False,
    ) -> None:
        self._selected_voice_key.set(key)
        self._backend_button.config(
            text=f"Voice: {label}…" if loading else f"Voice: {label} ▾",
            state="disabled" if loading else "normal",
            fg=ACCENT if key == "supertonic" else DIM_FOREGROUND,
        )
        self._resize(MIN_IDLE_HEIGHT)
        log_event(
            logger,
            logging.INFO,
            "player.voice.updated",
            voice_key=key,
            voice_label=label,
            loading=loading,
        )

    def _show_voice_menu(self) -> None:
        if not self._voice_options:
            return
        try:
            self._voice_menu.tk_popup(
                self._backend_button.winfo_rootx(),
                self._backend_button.winfo_rooty()
                + self._backend_button.winfo_height(),
            )
        finally:
            self._voice_menu.grab_release()

    def show_backend_error(self, message: str) -> None:
        self._status.config(text=f"Voice engine unavailable: {message}", fg=RED)
        self.show()

    def show_backend_loading(self) -> None:
        self._status.config(text="Voice engine is still loading…", fg=ACCENT)
        self.show()

    def show_capture_started(self) -> None:
        log_event(logger, logging.INFO, "player.hotkey_capture.started")
        self._status.config(text="⌨  Press keys…  (Esc to cancel)", fg=ACCENT)
        self._hotkey_button.config(text="…")

    def show_capture_preview(self, hotkey: str) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "player.hotkey_capture.preview",
            hotkey=hotkey,
        )
        self._status.config(text=f"⌨  {hotkey.upper()}", fg=ACCENT)
        self._hotkey_button.config(text=hotkey.upper())

    def show_capture_complete(self, hotkey: str) -> None:
        log_event(
            logger,
            logging.INFO,
            "player.hotkey_capture.completed",
            hotkey=hotkey,
        )
        self.set_hotkey(hotkey)
        self._status.config(text=f"✓  Hotkey set to  {hotkey.upper()}", fg=GREEN)
        self.after(2000, self.show_idle_hint)

    def show_idle_hint(self) -> None:
        target = "clipboard" if self._clipboard_mode else "selection or clipboard"
        log_event(
            logger,
            logging.DEBUG,
            "player.idle_hint.shown",
            target=target,
            hotkey=self._hotkey,
        )
        self._status.config(
            text=f"Press {self._hotkey.upper()} to read {target}", fg=DIM_FOREGROUND
        )
        self._hotkey_button.config(text=self._hotkey.upper())

    def set_playback(
        self, *, speaking: bool, paused: bool = False, text: str = ""
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "player.playback.updated",
            speaking=speaking,
            paused=paused,
            text_length=len(text),
        )
        if speaking and not paused:
            self._start_animation()
            if text != self._reader_text or not self._reader_frame.winfo_ismapped():
                self._show_reader(text)
            else:
                self._reader.tag_config("current", background=BUTTON_BACKGROUND)
            self._play_button.config(
                text="⏸ Pause",
                command=self._on_pause,
                state="normal",
                bg=BUTTON_BACKGROUND,
                fg=FOREGROUND,
            )
            self._stop_button.config(bg=RED, fg=BACKGROUND)
            self.show()
        elif speaking:
            self._stop_animation()
            self._reader.tag_config("current", background=READER_BACKGROUND)
            self._play_button.config(
                text="▶ Resume",
                command=self._on_resume,
                state="normal",
                bg=BUTTON_BACKGROUND,
                fg=GREEN,
            )
            self._stop_button.config(bg=RED, fg=BACKGROUND)
        else:
            self._stop_animation()
            hint = "Done  •  Press hotkey to read again" if text else self._idle_hint()
            self._hide_reader(hint)
            self._play_button.config(
                text="▶ Replay",
                command=self._on_play,
                state="normal" if text else "disabled",
                bg=BUTTON_BACKGROUND,
                fg=FOREGROUND,
            )
            self._stop_button.config(bg=BUTTON_BACKGROUND, fg=RED)
            if self._auto_hide:
                self.after_idle(self.hide)

    def highlight_word(self, position: int, length: int) -> None:
        generation = self._reader_generation
        log_event(
            logger,
            logging.DEBUG,
            "player.word_highlight.queued",
            position=position,
            length=length,
            reader_generation=generation,
        )

        def update() -> None:
            if generation != self._reader_generation:
                log_event(
                    logger,
                    logging.DEBUG,
                    "player.word_highlight.stale",
                    queued_generation=generation,
                    current_generation=self._reader_generation,
                )
                return
            self._reader.config(state="normal")
            self._reader.tag_remove("current", "1.0", "end")
            self._reader.tag_add(
                "current", f"1.0+{position}c", f"1.0+{position + length}c"
            )
            self._reader.see(f"1.0+{position}c")
            self._reader.config(state="disabled")
            log_event(
                logger,
                logging.DEBUG,
                "player.word_highlight.applied",
                position=position,
                length=length,
            )

        self.call_soon(update)

    def _build_title_row(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=BACKGROUND)
        row.pack(fill="x")
        tk.Label(
            row,
            text=f"🔊 {self._app_name}",
            bg=BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        self._animation_label = tk.Label(
            row,
            text="",
            bg=BACKGROUND,
            fg=GREEN,
            font=("Segoe UI", 9),
            width=2,
            anchor="w",
        )
        self._animation_label.pack(side="left", padx=(4, 0))
        self._title_button(row, "✕", self.hide).pack(side="right")
        self._title_button(row, "–", self._minimize).pack(side="right")

    def _build_status(self, parent: tk.Frame) -> None:
        self._status = tk.Label(
            parent,
            text=self._idle_hint(),
            bg=BACKGROUND,
            fg=DIM_FOREGROUND,
            font=("Segoe UI", 8),
            wraplength=STATUS_WRAP_LENGTH,
            justify="left",
            anchor="w",
        )
        self._status.pack(fill="x", pady=(3, 5))

    def _build_reader(self, parent: tk.Frame) -> None:
        self._reader_frame = tk.Frame(parent, bg=READER_BACKGROUND)
        self._reader = tk.Text(
            self._reader_frame,
            height=9,
            bg=READER_BACKGROUND,
            fg=FOREGROUND,
            font=("Segoe UI", 9),
            wrap="word",
            relief="flat",
            bd=0,
            state="disabled",
            padx=6,
            pady=5,
            cursor="arrow",
        )
        self._reader.tag_config(
            "structured_line",
            lmargin1=8,
            lmargin2=8,
            spacing1=3,
            spacing3=5,
        )
        self._reader.tag_config(
            "bullet_line",
            lmargin1=8,
            lmargin2=24,
        )
        self._reader.tag_config(
            "current",
            background=BUTTON_BACKGROUND,
            foreground="#ffffff",
        )
        self._reader.pack(fill="both", expand=True)
        self._debug_frame = tk.Frame(parent, bg=READER_BACKGROUND, padx=6, pady=4)
        self._debug_metrics = tk.Label(
            self._debug_frame,
            text="Speech diagnostics waiting for chunks…",
            height=2,
            bg=READER_BACKGROUND,
            fg=DIM_FOREGROUND,
            font=("Consolas", 7),
            justify="left",
            anchor="w",
        )
        self._debug_metrics.pack(fill="x")

    def _build_controls(
        self,
        parent: tk.Frame,
        *,
        on_toggle_clipboard: Callable[[], None],
        on_toggle_auto_hide: Callable[[], None],
        on_toggle_debug: Callable[[], None],
        on_capture_hotkey: Callable[[], None],
    ) -> None:
        self._control_row = tk.Frame(parent, bg=BACKGROUND)
        # Reserve the controls at the bottom so an expanding reader or debug
        # panel can never push playback controls outside the client area.
        self._control_row.pack(side="bottom", fill="x")

        read_wrapper = tk.Frame(self._control_row, bg=BUTTON_BORDER, padx=1, pady=1)
        read_wrapper.pack(side="left", padx=(0, 6))
        self._read_button = self._control_button(
            read_wrapper, "▶ Read", GREEN, self._on_read
        )
        self._read_button.pack()

        play_wrapper = tk.Frame(self._control_row, bg=BUTTON_BORDER, padx=1, pady=1)
        play_wrapper.pack(side="left", padx=(0, 6))
        self._play_button = self._control_button(
            play_wrapper, "▶ Replay", FOREGROUND, self._on_play
        )
        self._play_button.pack()

        stop_wrapper = tk.Frame(self._control_row, bg=BUTTON_BORDER, padx=1, pady=1)
        stop_wrapper.pack(side="left")
        self._stop_button = self._control_button(
            stop_wrapper, "■ Stop", RED, self._on_stop
        )
        self._stop_button.pack()

        self._hotkey_button = self._small_button(
            self._control_row, self._hotkey.upper(), on_capture_hotkey
        )
        self._hotkey_button.pack(side="right")
        self._clipboard_button = self._small_button(
            self._control_row, "Mode: Auto", on_toggle_clipboard
        )
        self._clipboard_button.pack(side="right", padx=(0, 4))
        backend_label = (
            "Supertonic" if self._speech_backend == "supertonic" else "Windows"
        )
        self._voice_menu = tk.Menu(
            self,
            tearoff=False,
            bg=BUTTON_BACKGROUND,
            fg=FOREGROUND,
            activebackground=ACCENT,
            activeforeground=BACKGROUND,
            disabledforeground=DIM_FOREGROUND,
            relief="flat",
            bd=1,
            font=("Segoe UI", 9),
        )
        self._backend_button = self._small_button(
            self._control_row,
            f"Voice: {backend_label} ▾",
            self._show_voice_menu,
        )
        self._backend_button.config(
            fg=ACCENT if self._speech_backend == "supertonic" else DIM_FOREGROUND
        )
        self._backend_button.pack(side="right", padx=(0, 4))
        self._auto_hide_button = self._small_button(
            self._control_row,
            f"Auto hide: {'On' if self._auto_hide else 'Off'}",
            on_toggle_auto_hide,
        )
        self._auto_hide_button.config(
            fg=ACCENT if self._auto_hide else DIM_FOREGROUND,
            font=("Segoe UI", 7, "bold" if self._auto_hide else "normal"),
        )
        self._auto_hide_button.pack(side="right", padx=(0, 4))
        self._debug_button = self._small_button(
            self._control_row,
            f"Debug: {'On' if self._debug_enabled else 'Off'}",
            on_toggle_debug,
        )
        self._debug_button.config(
            fg=ACCENT if self._debug_enabled else DIM_FOREGROUND,
            font=("Segoe UI", 7, "bold" if self._debug_enabled else "normal"),
        )
        self._debug_button.pack(side="right", padx=(0, 4))

    def _show_reader(self, text: str) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "player.reader.shown",
            text_length=len(text),
        )
        self._reader_generation += 1
        self._reader_text = text
        self._reader.config(state="normal")
        self._reader.delete("1.0", "end")
        self._reader.insert("1.0", text)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                self._reader.tag_add(
                    "structured_line",
                    f"{line_number}.0",
                    f"{line_number}.end",
                )
                if line.startswith("• "):
                    self._reader.tag_add(
                        "bullet_line",
                        f"{line_number}.0",
                        f"{line_number}.end",
                    )
        self._reader.tag_remove("current", "1.0", "end")
        self._reader.tag_config("current", background=BUTTON_BACKGROUND)
        self._reader.config(state="disabled")
        if not self._reader_frame.winfo_ismapped():
            self._status.pack_forget()
            self._reader_frame.pack(
                fill="both",
                expand=True,
                pady=(3, 5),
                before=self._control_row,
            )
        if self._debug_enabled and not self._debug_frame.winfo_ismapped():
            self._debug_frame.pack(fill="x", pady=(0, 5), before=self._control_row)
        # Measure only after every speaking-mode panel has been inserted.
        self._resize(
            MIN_DEBUG_READING_HEIGHT
            if self._debug_enabled
            else MIN_READING_HEIGHT
        )
        self._control_row.lift()

    def _clear_chunk_tags(self) -> None:
        self._reader.config(state="normal")
        self._reader.tag_remove("debug_active_chunk", "1.0", "end")
        for index in self._debug.chunks:
            self._reader.tag_remove(f"debug_chunk_{index}", "1.0", "end")
        self._reader.config(state="disabled")

    def _apply_chunk_tags(self, active: SpeechDebugEvent | None = None) -> None:
        if not self._debug_enabled or not self._reader_text:
            return
        self._reader.config(state="normal")
        self._reader.tag_remove("debug_active_chunk", "1.0", "end")
        for index, event in self._debug.chunks.items():
            tag = f"debug_chunk_{index}"
            self._reader.tag_config(
                tag,
                underline=True,
                foreground=CHUNK_COLOURS[index % len(CHUNK_COLOURS)],
            )
            self._reader.tag_add(
                tag,
                f"1.0+{event.text_offset}c",
                f"1.0+{event.text_offset + event.text_length}c",
            )
        self._reader.tag_config(
            "debug_active_chunk", background="#3b4261", foreground="#ffffff"
        )
        if active and active.chunk_index is not None:
            self._reader.tag_add(
                "debug_active_chunk",
                f"1.0+{active.text_offset}c",
                f"1.0+{active.text_offset + active.text_length}c",
            )
            self._reader.tag_raise("current")
            self._reader.see(f"1.0+{active.text_offset}c")
        self._reader.config(state="disabled")

    def _render_debug_metrics(self, event: SpeechDebugEvent | None = None) -> None:
        old_required_height = self._debug_frame.winfo_reqheight()
        text, is_underrun = self._debug.metrics(event)
        self._debug_metrics.config(
            text=text,
            fg=RED if is_underrun else DIM_FOREGROUND,
        )
        self.update_idletasks()
        if (
            self._debug_enabled
            and self._reader_frame.winfo_ismapped()
            and self._debug_frame.winfo_reqheight() != old_required_height
        ):
            self._resize(MIN_DEBUG_READING_HEIGHT)
            self._control_row.lift()

    def _hide_reader(self, hint: str) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "player.reader.hidden",
            hint=hint,
        )
        self._reader_generation += 1
        self._reader_frame.pack_forget()
        self._debug_frame.pack_forget()
        self._status.config(text=hint, fg=DIM_FOREGROUND)
        self._status.pack(fill="x", pady=(3, 5), before=self._control_row)
        self._resize(MIN_IDLE_HEIGHT)

    def _start_animation(self) -> None:
        log_event(logger, logging.DEBUG, "player.animation.started")
        self._stop_animation()
        self._animation_frame = 0
        self._animation_tick()

    def _animation_tick(self) -> None:
        self._animation_label.config(text=SPINNER[self._animation_frame % len(SPINNER)])
        self._animation_frame += 1
        self._animation_job = self.after(80, self._animation_tick)

    def _stop_animation(self) -> None:
        if self._animation_job:
            try:
                self.after_cancel(self._animation_job)
            except tk.TclError:
                pass
            self._animation_job = None
            log_event(logger, logging.DEBUG, "player.animation.stopped")
        if hasattr(self, "_animation_label"):
            self._animation_label.config(text="")

    def _idle_hint(self) -> str:
        target = "clipboard" if self._clipboard_mode else "selection or clipboard"
        return (
            f"Press {self._hotkey.upper()} to read {target}"
            f"  •  {self._ocr_hotkey.upper()} for OCR"
        )

    def _drain_callbacks(self) -> None:
        drained = 0
        try:
            while True:
                self._callbacks.get_nowait()()
                drained += 1
        except Empty:
            pass
        except Exception:
            log_exception(
                logger,
                "player.callback.failed",
                callbacks_completed=drained,
            )
        if drained:
            log_event(
                logger,
                logging.DEBUG,
                "player.callbacks.drained",
                count=drained,
            )
        try:
            self.after(20, self._drain_callbacks)
        except tk.TclError:
            pass

    def _required_size(self, minimum_height: int) -> tuple[int, int]:
        self.update_idletasks()
        width = max(WINDOW_WIDTH, self._content.winfo_reqwidth())
        height = max(minimum_height, self._content.winfo_reqheight())
        return width, height

    def _resize(self, minimum_height: int) -> None:
        current_bottom = self.winfo_y() + self.winfo_height()
        width, height = self._required_size(minimum_height)
        new_y = max(0, current_bottom - height)
        max_x = max(0, self.winfo_screenwidth() - width)
        new_x = min(max(0, self.winfo_x()), max_x)
        self.geometry(f"{width}x{height}+{new_x}+{new_y}")
        log_event(
            logger,
            logging.DEBUG,
            "player.resized_to_content",
            width=width,
            height=height,
            requested_width=self._content.winfo_reqwidth(),
            requested_height=self._content.winfo_reqheight(),
            minimum_height=minimum_height,
            scaling=round(float(self.tk.call("tk", "scaling")), 3),
        )

    def _begin_drag(self, event: tk.Event) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "player.drag.started",
            x=event.x,
            y=event.y,
        )
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag(self, event: tk.Event) -> None:
        self.geometry(
            f"+{self.winfo_x() + event.x - self._drag_x}"
            f"+{self.winfo_y() + event.y - self._drag_y}"
        )

    def _minimize(self) -> None:
        log_event(logger, logging.INFO, "player.minimized")
        self._user_minimized = True
        self.overrideredirect(False)
        self.iconify()

    def _on_map(self, _event: tk.Event) -> None:
        if self.state() == "normal" and self._user_minimized:
            log_event(logger, logging.INFO, "player.restored")
            self._user_minimized = False
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.after_idle(self._enable_no_activate)

    @staticmethod
    def _title_button(
        parent: tk.Frame, text: str, command: Callable[[], None]
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            bg=BACKGROUND,
            fg=DIM_FOREGROUND,
            relief="flat",
            bd=0,
            font=("Segoe UI", 9),
            cursor="hand2",
            activebackground=READER_BACKGROUND,
            activeforeground=FOREGROUND,
            command=command,
        )

    @staticmethod
    def _control_button(
        parent: tk.Frame, text: str, foreground: str, command: Callable[[], None]
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            bg=BUTTON_BACKGROUND,
            fg=foreground,
            activebackground=BUTTON_BORDER,
            activeforeground=foreground,
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
            command=command,
        )

    @staticmethod
    def _small_button(
        parent: tk.Frame, text: str, command: Callable[[], None]
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            bg=BACKGROUND,
            fg=DIM_FOREGROUND,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 7),
            command=command,
        )
