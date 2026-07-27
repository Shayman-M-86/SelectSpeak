import ctypes
import logging
import os
import tkinter as tk
from collections.abc import Callable
from queue import Empty, SimpleQueue

from ..logging_setup import log_event, log_exception

logger = logging.getLogger(__name__)

BACKGROUND = "#1e1e2e"
READER_BACKGROUND = "#313244"
BUTTON_BACKGROUND = "#45475a"
BUTTON_BORDER = "#585b70"
FOREGROUND = "#cdd6f4"
DIM_FOREGROUND = "#6c7086"
GREEN = "#a6e3a1"
RED = "#f38ba8"
ACCENT = "#89b4fa"
WINDOW_WIDTH = 440
IDLE_HEIGHT = 92
READING_HEIGHT = 250
STATUS_WRAP_LENGTH = WINDOW_WIDTH - 22
SPINNER = ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷")
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_SWP_REFRESH_FRAME_NO_ACTIVATE = 0x0037


class PlayerWindow(tk.Tk):
    def __init__(
        self,
        *,
        app_name: str,
        hotkey: str,
        on_play: Callable[[], None],
        on_read: Callable[[], None],
        on_pause: Callable[[], None],
        on_resume: Callable[[], None],
        on_stop: Callable[[], None],
        on_toggle_clipboard: Callable[[], None],
        on_capture_hotkey: Callable[[], None],
    ) -> None:
        super().__init__()
        self._app_name = app_name
        self._hotkey = hotkey
        self._clipboard_mode = False
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

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(
            f"{WINDOW_WIDTH}x{IDLE_HEIGHT}"
            f"+{screen_width - WINDOW_WIDTH - 20}"
            f"+{screen_height - IDLE_HEIGHT - 60}"
        )
        self.bind("<ButtonPress-1>", self._begin_drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Map>", self._on_map)

        pad = tk.Frame(self, bg=BACKGROUND, padx=10, pady=8)
        pad.pack(fill="both", expand=True)
        self._build_title_row(pad)
        self._build_status(pad)
        self._build_reader(pad)
        self._build_controls(
            pad,
            on_toggle_clipboard=on_toggle_clipboard,
            on_capture_hotkey=on_capture_hotkey,
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

    def _build_controls(
        self,
        parent: tk.Frame,
        *,
        on_toggle_clipboard: Callable[[], None],
        on_capture_hotkey: Callable[[], None],
    ) -> None:
        self._control_row = tk.Frame(parent, bg=BACKGROUND)
        self._control_row.pack(fill="x")

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
            self._resize(READING_HEIGHT)

    def _hide_reader(self, hint: str) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "player.reader.hidden",
            hint=hint,
        )
        self._reader_generation += 1
        self._reader_frame.pack_forget()
        self._status.config(text=hint, fg=DIM_FOREGROUND)
        self._status.pack(fill="x", pady=(3, 5), before=self._control_row)
        self._resize(IDLE_HEIGHT)

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
        return f"Press {self._hotkey.upper()} to read {target}"

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

    def _resize(self, height: int) -> None:
        current_bottom = self.winfo_y() + self.winfo_height()
        new_y = max(0, current_bottom - height)
        self.geometry(f"{WINDOW_WIDTH}x{height}+{self.winfo_x()}+{new_y}")

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
