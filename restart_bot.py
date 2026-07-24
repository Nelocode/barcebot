"""
Script independiente para reiniciar el bot de Telegram.
Se ejecuta como subproceso separado para no matar el panel Flask ni Hermes.
Usa PowerShell para listar procesos (funciona en Windows desde cualquier shell).
"""
import os
import sys
import time
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent


def find_bot_pids():
    """Encuentra PIDs de procesos bot.py usando PowerShell (funciona en Windows)."""
    pids = []
    try:
        ps_cmd = (
            'powershell.exe -Command "'
            'Get-CimInstance Win32_Process -Filter \\"name = \'python.exe\'\\" '
            '| Select-Object ProcessId,CommandLine '
            '| ConvertTo-Csv -NoTypeInformation'
            '"'
        )
        result = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=10, shell=True)
        for line in result.stdout.splitlines():
            if '"' in line:  # CSV line
                parts = line.split('","')
                if len(parts) >= 2:
                    cmdline = parts[1].strip('"').lower()
                    pid_str = parts[0].strip('"')
                    if "bot.py" in cmdline and "restart_bot.py" not in cmdline:
                        if pid_str.isdigit():
                            pids.append(int(pid_str))
    except Exception as e:
        print(f"Warning finding bot PIDs: {e}")
    return pids


def kill_bot_processes():
    """Mata solo procesos bot.py por PID, no todos los python."""
    pids = find_bot_pids()
    if not pids:
        print("No hay procesos bot.py activos")
        return

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                          capture_output=True, timeout=5)
            print(f"Killed bot.py PID {pid}")
        except Exception as e:
            print(f"Error killing PID {pid}: {e}")

    time.sleep(1)


def start_bot():
    """Lanza el bot como proceso independiente DETACHED (sobrevive al padre)."""
    token = os.environ.get("AUTOREPLY_BOT_TOKEN")
    if not token:
        print("ERROR: AUTOREPLY_BOT_TOKEN no está configurado")
        return False

    python = sys.executable
    bot_script = str(BASE_DIR / "bot.py")
    log_file = str(BASE_DIR / "bot_runner.log")

    # Limpiar log anterior
    try:
        with open(log_file, "w") as f:
            f.write(f"=== Bot restart at {time.ctime()} ===\n")
    except:
        pass

    env = os.environ.copy()
    env["AUTOREPLY_BOT_TOKEN"] = token

    try:
        proc = subprocess.Popen(
            [python, bot_script],
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
        print(f"Bot launched with PID {proc.pid}")
        return True
    except Exception as e:
        print(f"Error launching bot: {e}")
        return False


if __name__ == "__main__":
    print("=== Restarting bot ===")
    kill_bot_processes()
    success = start_bot()
    if success:
        print("Bot restarted successfully")
        sys.exit(0)
    else:
        print("Bot restart FAILED")
        sys.exit(1)
