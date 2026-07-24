"""
Script independiente para reiniciar el bot de Telegram.
Funciona en Windows y Linux.
"""
import os
import sys
import time
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent


def find_bot_pids():
    """Encuentra PIDs de procesos bot.py."""
    pids = []
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ['powershell.exe', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
                 "Select-Object ProcessId,CommandLine | ConvertTo-Csv -NoTypeInformation"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if '"' in line and 'bot.py' in line.lower() and 'restart_bot.py' not in line.lower():
                    parts = line.split('","')
                    if len(parts) >= 2 and parts[0].strip('"').isdigit():
                        pids.append(int(parts[0].strip('"')))
        else:
            result = subprocess.run(
                ["pgrep", "-f", "bot.py"], capture_output=True, text=True, timeout=5
            )
            for pid_str in result.stdout.strip().splitlines():
                if pid_str.strip().isdigit():
                    pid = int(pid_str.strip())
                    # No matarnos a nosotros mismos
                    if pid != os.getpid():
                        pids.append(pid)
    except:
        pass
    return pids


def main():
    token = os.environ.get("AUTOREPLY_BOT_TOKEN")
    if not token:
        # Intentar leer de .env.local
        env_file = BASE_DIR / "data" / ".env.local"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("AUTOREPLY_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    
    if not token:
        print("ERROR: AUTOREPLY_BOT_TOKEN no encontrado")
        sys.exit(1)

    print("=== Restarting bot ===")
    
    # Matar procesos existentes
    pids = find_bot_pids()
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], 
                             capture_output=True, timeout=5)
            else:
                os.kill(pid, 15)  # SIGTERM
            print(f"Killed bot.py PID {pid}")
        except:
            pass
    
    time.sleep(2)
    
    # Lanzar nuevo bot
    bot_script = BASE_DIR / "bot.py"
    log_file = BASE_DIR / "bot_runner.log"
    
    with open(log_file, "a") as f:
        env = os.environ.copy()
        env["AUTOREPLY_BOT_TOKEN"] = token
        
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(
                [sys.executable, str(bot_script)],
                stdout=f, stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                startupinfo=startupinfo
            )
        else:
            proc = subprocess.Popen(
                [sys.executable, str(bot_script)],
                stdout=f, stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True
            )
        
        print(f"Bot launched with PID {proc.pid}")
    
    print("Bot restarted successfully")


if __name__ == "__main__":
    main()
