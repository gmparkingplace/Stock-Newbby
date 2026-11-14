@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0desktop_qt.py" %*
) else (
  python "%~dp0desktop_qt.py" %*
)
if errorlevel 1 pause
