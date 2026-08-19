import logging
import threading
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

from .system_theme import apps_use_dark_theme

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
        logger.info("tray.created app_name=%s hotkey=%s", app_name, hotkey)

    @property
    def _title(self) -> str:
        return f"{self._app_name} — {self._hotkey.upper()}"

    def start(self) -> None:
        logger.info("tray.starting")
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="SystemTray")
        self._thread.start()
        logger.info("tray.started")

    def stop(self) -> None:
        logger.info("tray.stopping")
        self._icon.stop()
        logger.info("tray.stopped")

    def update_hotkey(self, hotkey: str) -> None:
        logger.info("tray.hotkey.updated previous_hotkey=%s new_hotkey=%s", self._hotkey, hotkey)
        self._hotkey = hotkey
        self._icon.title = self._title
        self._icon.update_menu()

    def _show(self, _icon: object, _item: object) -> None:
        logger.info("tray.show_selected")
        self._on_show()

    def _quit(self, _icon: object, _item: object) -> None:
        logger.info("tray.quit_selected")
        self._on_quit()

    def _hotkey_label(self, _item: object) -> str:
        return f"Hotkey: {self._hotkey.upper()}"

    @staticmethod
    def _create_icon() -> Image.Image:
        """Draw a monochrome speaker, as Windows notification icons are.

        Shell icons take the tray's own contrast rather than an app colour, so
        this follows the theme: light glyph on dark taskbars and vice versa.
        """
        logger.debug("tray.icon.creating")
        dark = apps_use_dark_theme()
        # The taskbar is the opposite polarity to the app surface.
        fill = (255, 255, 255, 255) if dark else (0, 0, 0, 255)
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        drawing = ImageDraw.Draw(image)
        # Speaker body and cone.
        drawing.rectangle([12, 26, 22, 38], fill=fill)
        drawing.polygon([(22, 38), (34, 50), (34, 14), (22, 26)], fill=fill)
        # Two sound arcs.
        for offset, width in ((0, 4), (10, 4)):
            drawing.arc(
                [34 - offset, 18 - offset // 2, 46 + offset, 46 + offset // 2],
                start=300,
                end=60,
                fill=fill,
                width=width,
            )
        logger.debug("tray.icon.created theme=%s", "dark" if dark else "light")
        return image
