# PyInstaller spec for FinanzIAs.
#
# Build with:
#     python -m pip install pyinstaller
#     pyinstaller packaging/finanzias.spec --clean --noconfirm
#
# Output: dist/FinanzIAs/ (one-folder bundle).
#
# Notes
# -----
# - We use one-folder mode rather than ``--onefile`` because PyInstaller's
#   one-file extraction is significantly slower at startup and breaks file-
#   path assumptions (e.g. SQLite DB next to the executable).
# - ``hiddenimports`` lists modules PyInstaller's static analysis can't find
#   on its own — typically those imported via ``__import__`` or registered
#   as plugins by their host library (yfinance/SQLAlchemy/matplotlib).
# - ``collect_data_files`` is used for libraries that ship resource files
#   alongside their .py modules (matplotlib backends, mplfinance styles).

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # type: ignore[name-defined]   # SPECPATH injected by PyInstaller

block_cipher = None

hiddenimports = [
    "PyQt6.sip",
    "sqlalchemy.dialects.sqlite",
    "yfinance",
    "pandas_ta",
    "hmmlearn._hmmc",
    "arch.univariate",
    "matplotlib.backends.backend_qtagg",
    "openpyxl.styles.numbers",
    *collect_submodules("reportlab"),
]

datas = []
datas += collect_data_files("matplotlib")
datas += collect_data_files("mplfinance")
datas += collect_data_files("pandas_ta")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Big test/dev modules we never need at runtime
        "pytest", "pytest_qt", "ruff", "mypy", "alembic",
        "IPython", "jupyter", "notebook",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FinanzIAs",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX often breaks PyQt6 plugins
    console=False,            # GUI app — no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                # set to a .ico path when an icon is added
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FinanzIAs",
)
