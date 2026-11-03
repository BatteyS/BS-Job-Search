@echo off
rem Opens the page: double-click this file in File Explorer. Keep the window
rem open while you use the page; closing it stops the page.
cd /d "%~dp0"
set "UV=uv"
where uv >nul 2>nul || set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not "%UV%"=="uv" if not exist "%UV%" goto nouv
"%UV%" run ui/server.py %*
if errorlevel 1 pause
exit /b

:nouv
echo The page needs uv, which is not installed. Install it with:
echo.
echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
echo.
echo then open this file again. More at https://docs.astral.sh/uv/
pause
exit /b 1
