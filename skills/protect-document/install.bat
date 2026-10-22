@echo off
rem One-time setup: installs Python (if missing) and the libraries the tool
rem needs, then puts a "Protect document" shortcut on the desktop.
chcp 65001 >nul
setlocal
echo === Document protection tool - setup ===
echo.

call :findpy
if not defined PY (
  echo Python was not found. Installing Python with winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  set "PATH=%LOCALAPPDATA%\Programs\Python\Launcher;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
  call :findpy
)
if not defined PY (
  echo.
  echo Could not install Python automatically.
  echo Install it from https://www.python.org/downloads/ - tick "Add Python to PATH" -
  echo then run install.bat again.
  echo.
  pause
  exit /b 1
)

echo.
echo Installing libraries...
%PY% -m pip install --upgrade -r "%~dp0scripts\requirements.txt"
if errorlevel 1 (
  echo.
  echo Library installation failed - see the messages above.
  pause
  exit /b 1
)

echo.
echo Creating a desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Protect document.lnk'); $s.TargetPath = '%~dp0protect.bat'; $s.WorkingDirectory = '%~dp0'; $s.Save()"

echo.
echo Done. Drag a Word or PDF file onto "Protect document" on your desktop.
echo Keep this folder where it is - the shortcut points to it.
echo.
pause
exit /b 0

:findpy
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3" && exit /b 0
python -c "import sys" >nul 2>nul && set "PY=python"
exit /b 0
