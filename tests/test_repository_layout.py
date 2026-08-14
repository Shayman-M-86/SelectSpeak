from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
BUILD_TOOLS_ROOT = PROJECT_ROOT / "build-tools"
WORKFLOWS_ROOT = PROJECT_ROOT / ".github" / "workflows"

BUILD_GROUPS = {
    "app": {
        "pyinstaller_entrypoint.py",
        "SelectSpeak.manifest",
        "SelectSpeak.spec",
        "version_info.txt",
    },
    "installer": {"SelectSpeak.iss", "build_installer.ps1", "smoke_test.ps1"},
    "native": {"build.ps1", "build_helpers.ps1"},
    "runtime": {"install_speech_runtime.ps1"},
    "security": {"README.md", "audit_dependencies.ps1"},
    "supertonic": {"build_payload.py", "install_payload.ps1"},
    "tools": {
        "collect_licenses.py",
        "create_icon.py",
        "stage_native.ps1",
        "verify_dist.py",
        "verify_windows_metadata.ps1",
    },
}


def test_application_source_is_grouped_by_language() -> None:
    assert (PROJECT_ROOT / "src" / "python" / "selectspeak" / "__main__.py").is_file()
    assert (PROJECT_ROOT / "src" / "native" / "CMakeLists.txt").is_file()
    assert not (PROJECT_ROOT / "main.py").exists()
    assert not (PROJECT_ROOT / "src" / "selectspeak").exists()
    assert not (PROJECT_ROOT / "native").exists()


def test_build_files_are_grouped_by_responsibility() -> None:
    for directory, names in BUILD_GROUPS.items():
        actual = {path.name for path in (BUILD_TOOLS_ROOT / directory).iterdir() if path.is_file()}
        assert actual == names


def test_generated_output_is_separate_from_build_tooling() -> None:
    ignored_paths = {
        line.strip() for line in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    assert ".build/" in ignored_paths
    assert "build/" not in ignored_paths
    assert "build-tools/" not in ignored_paths
    assert not (PROJECT_ROOT / "build").exists()
    assert not (PROJECT_ROOT / "packaging").exists()


def test_root_entry_points_moved_to_scripts() -> None:
    assert (PROJECT_ROOT / "scripts" / "install.ps1").is_file()
    assert (PROJECT_ROOT / "scripts" / "run.vbs").is_file()
    assert not (PROJECT_ROOT / "install.ps1").exists()
    assert not (PROJECT_ROOT / "run.vbs").exists()


def test_github_workflows_cover_release_quality_gates() -> None:
    assert {path.name for path in WORKFLOWS_ROOT.glob("*.yml")} == {
        "ci.yml",
        "distribution.yml",
    }
