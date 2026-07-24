@echo off
rem AutoReply Bot Gateway — Telegram commercial autoresponder
cd /d %~dp0
setlocal
set "AUTOREPLY_BOT_TOKEN=TU_TOKEN_AQUI"
set "PYTHONIOENCODING=utf-8"
set "VIRTUAL_ENV=C:\Users\nelso\AppData\Local\hermes\hermes-agent\venv"
C:\Users\nelso\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe bot.py
exit /b 0
