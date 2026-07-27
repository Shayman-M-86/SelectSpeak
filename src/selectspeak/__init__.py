"""SelectSpeak Windows text-to-speech application."""


def main() -> None:
    """Start SelectSpeak without importing Windows integrations eagerly."""
    import logging

    from .logging_setup import configure_logging, log_event

    log_path = configure_logging()
    log_event(
        logging.getLogger("selectspeak"),
        logging.INFO,
        "app.entrypoint",
        log_file=str(log_path),
    )
    from .app import main as run

    run()
