"""SelectSpeak Windows text-to-speech application."""


def main() -> None:
    """Start SelectSpeak without importing Windows integrations eagerly."""
    import logging

    from .config import DEFAULT_CONFIG
    from .logging_setup import configure_logging

    log_path = configure_logging(DEFAULT_CONFIG.logging)
    if log_path is not None:
        logging.getLogger(__name__).info("app.entrypoint log_file=%s", log_path)
    from .app import main as run

    run()
