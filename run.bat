@echo off
cd /d "%~dp0"

:: 1. Launch Electron Visual Window
set "ELECTRON_DIR=%~dp0visual"
set "ELECTRON_EXE=%ELECTRON_DIR%\node_modules\electron\dist\electron.exe"

if exist "%ELECTRON_EXE%" (
    start "" /D "%ELECTRON_DIR%" "%ELECTRON_EXE%" .
) else (
    where npx >nul 2>nul && (
        start "" /D "%ELECTRON_DIR%" npx electron .
    )
)

:: 2. Find Python 3.11-3.14
set "PYW="
for %%v in (3.14 3.13 3.12 3.11) do if not defined PYW py -%%v -c "" >nul 2>nul && set "PYW=pyw -%%v"
if not defined PYW where pyw >nul 2>nul && set "PYW=pyw"
if not defined PYW set "PYW=pythonw"

:: 3. Launch Python Assistant Backend
start "" %PYW% main.py
