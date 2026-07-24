@echo off
rem WhatsApp AutoReply Bot — Inicio rápido
rem El QR también se muestra en el panel admin http://localhost:5000
cd /d "%~dp0"
set "BOT_DIR=%~dp0"
echo ╔══════════════════════════════════════════════╗
echo ║   WhatsApp AutoReply Bot                     ║
echo ║   Abre http://localhost:5000 para ver el QR  ║
echo ║   o escanea el que aparece abajo             ║
echo ╚══════════════════════════════════════════════╝
echo.
node wa_bot.mjs
pause
