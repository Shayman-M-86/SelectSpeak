import logging
import threading
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

from ..logging_setup import log_event

logger = logging.getLogger(__name__)


class TrayController:
    def __init__(
        self,
        *,
        app_name: str,
        hotkey: str,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._app_name = app_name
        self._hotkey = hotkey
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            app_name,
            self._create_icon(),
            self._title,
            pystray.Menu(
                pystray.MenuItem("Show Player", self._show, default=True),
                pystray.MenuItem(self._hotkey_label, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )
        self._thread: threading.Thread | None = None
        log_event(
            logger,
            logging.INFO,
            "tray.created",
            app_name=app_name,
            hotkey=hotkey,
        )

    @property
    def _title(self) -> str:
        return f"{self._app_name} — {self._hotkey.upper()}"

    def start(self) -> None:
        log_event(logger, logging.INFO, "tray.starting")
        self._thread = threading.Thread(
            target=self._icon.run, daemon=True, name="SystemTray"
        )
        self._thread.start()
        log_event(logger, logging.INFO, "tray.started")

    def stop(self) -> None:
        log_event(logger, logging.INFO, "tray.stopping")
        self._icon.stop()
        log_event(logger, logging.INFO, "tray.stopped")

    def update_hotkey(self, hotkey: str) -> None:
        log_event(
            logger,
            logging.INFO,
            "tray.hotkey.updated",
            previous_hotkey=self._hotkey,
            new_hotkey=hotkey,
        )
        self._hotkey = hotkey
        self._icon.title = self._title
        self._icon.update_menu()

    def _show(self, _icon: object, _item: object) -> None:
        log_event(logger, logging.INFO, "tray.show_selected")
        self._on_show()

    def _quit(self, _icon: object, _item: object) -> None:
        log_event(logger, logging.INFO, "tray.quit_selected")
        self._on_quit()

    def _hotkey_label(self, _item: object) -> str:
        return f"Hotkey: {self._hotkey.upper()}"

    @staticmethod
    def _create_icon() -> Image.Image:
        log_event(logger, logging.DEBUG, "tray.icon.creating")
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        drawing = ImageDraw.Draw(image)
        drawing.ellipse([4, 4, 60, 60], fill="#89b4fa")
        drawing.polygon(
            [(20, 22), (20, 42), (30, 42), (44, 52), (44, 12), (30, 22)],
            fill="#1e1e2e",
        )
        log_event(logger, logging.DEBUG, "tray.icon.created")
        return image
