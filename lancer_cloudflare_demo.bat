@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python est introuvable. Installez Python ou ajoutez-le au PATH.
    pause
    exit /b 1
)

set "CLOUDFLARED="
where cloudflared >nul 2>&1
if not errorlevel 1 set "CLOUDFLARED=cloudflared"
if exist "%ProgramFiles(x86)%\cloudflared\cloudflared.exe" set "CLOUDFLARED=%ProgramFiles(x86)%\cloudflared\cloudflared.exe"

if not defined CLOUDFLARED (
    echo cloudflared est introuvable.
    echo Installation : winget install --id Cloudflare.cloudflared -e
    pause
    exit /b 1
)

if not exist ".env" (
    echo Le fichier .env est introuvable dans le dossier du projet.
    pause
    exit /b 1
)

echo Demarrage du serveur local de la Mini App...
start "Mini App Telegram - serveur local" /D "%~dp0" python serve_telegram_miniapp.py --broker deriv
timeout /t 2 /nobreak >nul

echo.
echo Le tunnel HTTPS va afficher une URL https://....trycloudflare.com
echo Copiez cette URL, ajoutez-la dans .env sous :
echo TELEGRAM_WEBAPP_URL=https://....trycloudflare.com
echo Puis ouvrez une deuxieme fenetre et lancez :
echo python live_trading.py --broker deriv --demo
echo.
echo Gardez cette fenetre ouverte. Le tunnel est temporaire et son URL
echo changera lors d'un prochain lancement.
echo.
"%CLOUDFLARED%" tunnel --protocol http2 --url http://127.0.0.1:8766

echo.
echo Le tunnel est arrete.
pause
