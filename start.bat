@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
) else (
  python "%~dp0run.py" %*
)
if errorlevel 1 pause
