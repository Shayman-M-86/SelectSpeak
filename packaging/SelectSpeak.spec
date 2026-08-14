from pathlib import Path


project_root = Path(SPECPATH).parent
icon_path = project_root / "build" / "packaging" / "SelectSpeak.ico"

analysis = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "pythoncom",
        "pywintypes",
        "win32com.client",
        "onnxruntime.capi._pybind_state",
    ],
    excludes=[
        # SelectSpeak consumes Supertonic waveforms directly. Its save_audio()
        # helper is the only path that needs soundfile/libsndfile/cffi.
        "_soundfile",
        "_soundfile_data",
        "soundfile",
        # Hugging Face can download the model over HTTP without its optional
        # Rust Xet accelerator, which otherwise adds a roughly 9 MiB binary.
        "hf_xet",
        # The tray icon is drawn in memory; it never decodes AVIF images.
        "PIL.AvifImagePlugin",
        # win32com's type-library tooling optionally imports the Pythonwin GUI.
        # SelectSpeak uses dynamic SAPI dispatch and never uses that GUI stack.
        "pywin",
        "win32ui",
        "fastapi",
        "pytest",
        "ruff",
        "ty",
        "uvicorn",
    ],
    noarchive=False,
)


def keep_optional_artifact(entry):
    name = entry[0].replace("\\", "/").casefold()
    return not (
        name == "_soundfile.pyd"
        or name.startswith("_soundfile_data/")
        or name == "hf_xet.pyd"
        or name.startswith("hf_xet/")
    )


analysis.binaries = [entry for entry in analysis.binaries if keep_optional_artifact(entry)]
analysis.datas = [entry for entry in analysis.datas if keep_optional_artifact(entry)]

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SelectSpeak",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path),
    version=str(project_root / "packaging" / "version_info.txt"),
    manifest=str(project_root / "packaging" / "SelectSpeak.manifest"),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="SelectSpeak",
    contents_directory="_internal",
)
