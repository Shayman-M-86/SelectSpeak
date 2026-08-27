from pathlib import Path


project_root = Path(SPECPATH).parent.parent
icon_path = project_root / ".build" / "packaging" / "SelectSpeak.ico"

analysis = Analysis(
    [str(Path(SPECPATH) / "pyinstaller_entrypoint.py")],
    pathex=[str(project_root / "src" / "python")],
    binaries=[],
    # The tray draws its icon from the logo at runtime, so ship the image
    # itself rather than only the .ico the executable is stamped with.
    datas=[(str(project_root / "logo" / "SelectSpeak-logo.png"), ".")],
    hiddenimports=[
        "pywintypes",
    ],
    excludes=[
        # The player is the WinUI process; nothing here draws with Tk, and the
        # Tcl/Tk runtime is large enough to be worth refusing explicitly.
        "tkinter",
        "_tkinter",
        # The neural engine is installed later as a versioned dependency layer.
        "huggingface_hub",
        "numpy",
        "onnxruntime",
        "supertonic",
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
        # Pythonwin's optional GUI stack is not used by SelectSpeak.
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
    basename = name.rsplit("/", 1)[-1]
    return not (
        basename == "_soundfile.pyd"
        or name.startswith("_soundfile_data/")
        or basename == "hf_xet.pyd"
        or name.startswith("hf_xet/")
        or basename == "mfc140u.dll"
        or basename == "win32ui.pyd"
        or basename.startswith("_avif.")
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
    version=str(Path(SPECPATH) / "version_info.txt"),
    manifest=str(Path(SPECPATH) / "SelectSpeak.manifest"),
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
