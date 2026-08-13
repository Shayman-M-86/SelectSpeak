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
    excludes=["fastapi", "pytest", "ruff", "ty", "uvicorn"],
    noarchive=False,
)

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
