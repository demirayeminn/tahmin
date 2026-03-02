@echo off
chcp 65001 > nul
echo.
echo Aginizdaki IP adresiniz:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%a
    setlocal enabledelayedexpansion
    set IP=!IP: =!
    echo   http://!IP!:8501
    endlocal
)
echo.
pause
