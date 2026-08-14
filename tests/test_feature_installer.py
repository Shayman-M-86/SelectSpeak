from pathlib import Path

from selectspeak.speech import feature_installer


def test_release_url_targets_the_matching_setup_version() -> None:
    assert feature_installer.supertonic_installer_url("2.3.4").endswith(
        "/releases/download/v2.3.4/SelectSpeak-Setup-2.3.4.exe"
    )


def test_local_installer_override_is_used(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "SelectSpeak-Setup.exe"
    installer.touch()
    monkeypatch.setenv("SELECTSPEAK_INSTALLER_PATH", str(installer))

    assert feature_installer.acquire_feature_installer() == installer.resolve()


def test_developer_build_uses_installer_from_dist(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "dist" / "SelectSpeak-Setup-2.3.4.exe"
    installer.parent.mkdir()
    installer.touch()
    monkeypatch.delenv("SELECTSPEAK_INSTALLER_PATH", raising=False)
    monkeypatch.setattr(feature_installer, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(feature_installer, "is_frozen", lambda: False)
    monkeypatch.setattr(feature_installer, "_registered_installer_path", lambda: None)

    assert feature_installer.acquire_feature_installer("2.3.4") == installer.resolve()


def test_installer_launch_preselects_supertonic(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "SelectSpeak-Setup.exe"
    installer.touch()
    calls: list[list[str]] = []

    def fake_popen(arguments: list[str]):
        calls.append(arguments)
        return object()

    monkeypatch.setattr(feature_installer.subprocess, "Popen", fake_popen)
    feature_installer.launch_supertonic_installer(installer)

    assert calls == [[str(installer), "/COMPONENTS=supertonic"]]
