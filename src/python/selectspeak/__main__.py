def main() -> None:
    """Run SelectSpeak through its package entry point."""
    from .app.startup import run_application

    run_application()


if __name__ == "__main__":
    main()
