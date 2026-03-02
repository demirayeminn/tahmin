@echo off
chcp 65001 > nul
title Stok Takip Sistemi

REM Proje klasoru
set "PROJE=C:\Users\Emin\Desktop\Ev-tahmin"

echo ============================================================
echo  STOK TAKIP SISTEMI
echo ============================================================
echo.

:: ── 1. Veri guncelleme ──────────────────────────────────────
echo [1/2] Entegra stok verisi cekiliyor ve alarmlar hesaplaniyor...
echo.

cd /d "%PROJE%"
python -m src.scheduler --once

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [UYARI] Veri guncelleme hata verdi. Onceki veriyle devam ediliyor.
    echo         Hata ayiklamak icin: python -m src.scheduler --once
    echo.
    pause
)

echo.
echo [OK] Veri guncelleme tamamlandi.
echo.

:: ── 2. Streamlit baslat ─────────────────────────────────────
echo [2/2] Dashboard baslatiliyor...
echo.
echo  Ayni agdaki baska bir cihazdan erismek icin:
echo  Bilgisayarin IP adresini ogrenin (cmd'de: ipconfig)
echo  Tarayicida: http://[IP_ADRESINIZ]:8501
echo.
echo  Bu bilgisayardan erisim: http://localhost:8501
echo.
echo  Kapatmak icin bu pencereyi kapatin veya Ctrl+C basin.
echo ============================================================
echo.

streamlit run "%PROJE%\dashboard\app.py" --server.port 8501 --server.address 0.0.0.0 --browser.gatherUsageStats false

pause
