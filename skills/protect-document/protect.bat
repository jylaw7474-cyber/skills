@echo off
rem Drag one or more PDF / Word files onto this file (or onto its desktop
rem shortcut). Double-click it to choose files from a dialog.
chcp 65001 >nul
setlocal
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python is not installed - run install.bat first.
  pause
  exit /b 1
)
%PY% "%~dp0scripts\protect_doc.py" %*
echo.
pause
