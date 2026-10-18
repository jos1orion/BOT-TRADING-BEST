@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python est introuvable. Installez Python ou ajoutez-le au PATH.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Le fichier .env est introuvable dans le dossier du projet.
    pause
    exit /b 1
)

echo Lancement du bot Deriv en mode DEMO et du serveur Mini App local...
echo Le serveur local ne rend pas encore la Mini App accessible dans Telegram :
echo une URL publique HTTPS sera necessaire pour cette etape.

start "Bot Deriv - DEMO" /D "%~dp0" python live_trading.py --broker deriv --demo
timeout /t 2 /nobreak >nul
start "Mini App Telegram - serveur local" /D "%~dp0" python serve_telegram_miniapp.py --broker deriv

echo Deux fenetres ont ete ouvertes. Laissez-les tourner.
echo Fermez leurs fenetres pour arreter les processus.
pause
