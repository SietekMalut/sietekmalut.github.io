@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Membuka katalog di http://localhost:8080/
echo Tekan Ctrl+C untuk menghentikan server.
echo.
start "" "http://localhost:8080/"
python -m http.server 8080
pause
