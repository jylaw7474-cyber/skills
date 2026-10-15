@echo off
rem Drag one or more PDF / Word files onto this file.
rem Double-click it to choose files from a dialog.
chcp 65001 >nul
python "%~dp0scripts\protect_doc.py" %*
echo.
pause
