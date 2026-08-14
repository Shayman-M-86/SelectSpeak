"""SelectSpeak Windows text-to-speech application."""

__version__ = "0.1.0"


def main() -> None:
    """Start SelectSpeak without importing Windows integrations eagerly."""
    from .app.startup import run_application

    run_application()
