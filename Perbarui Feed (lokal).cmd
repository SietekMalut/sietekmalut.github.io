@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  RSS SietekMalut - perbarui feed (lokal)
echo ============================================
echo.
python generator\generate.py %*
set KODE=%ERRORLEVEL%
echo.
if not "%KODE%"=="0" echo Selesai dengan kode %KODE%. Periksa pesan di atas.
pause
