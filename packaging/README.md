# Packaging FinanzIAs as a Windows executable

This folder contains the PyInstaller spec used to bundle FinanzIAs for
distribution. The output is a self-contained folder (`dist/FinanzIAs/`)
that runs without requiring Python to be installed on the target machine.

## Build steps

1. Activate the project's virtual environment so the build picks up the
   correct package versions:

   ```powershell
   .\venv\Scripts\activate
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. Build:

   ```powershell
   pyinstaller packaging\finanzias.spec --clean --noconfirm
   ```

3. The bundle lands in `dist\FinanzIAs\`. The launcher is
   `dist\FinanzIAs\FinanzIAs.exe`. Zip the whole folder for distribution.

## Notes

- **One-folder, not one-file.** One-file mode unpacks to a temp directory on
  every launch, which adds ~3-5 s of cold-start latency and breaks any code
  that assumes the SQLite DB lives next to the executable.
- **First-run database location.** The app creates `finanzias.db` inside the
  user's working directory on first launch. To pin it next to the exe,
  override `DB_PATH` via env var or edit `database/models.py`.
- **Icon.** Drop a `.ico` file in this folder and update `icon=` in
  `finanzias.spec`.
- **Antivirus false positives.** PyInstaller bundles sometimes get flagged
  by Windows Defender. Sign the executable with a code-signing certificate
  for production distribution.
- **CI builds.** A GitHub Actions workflow (Windows runner) can run the same
  spec; matrix-build for Python 3.11 / 3.12 if you want broader coverage.
