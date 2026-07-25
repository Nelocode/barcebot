"""Compatibilidad CLI para reiniciar únicamente el worker Telegram rastreado."""

from app import restart_telegram_worker


def main() -> int:
    started, message = restart_telegram_worker()
    print(message)
    return 0 if started else 1


if __name__ == "__main__":
    raise SystemExit(main())
