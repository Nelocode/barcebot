"""Narrow, recoverable migrations for persisted audio assets."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys


LEGACY_FRENCH_CALL_SHA256 = (
    "fb411378d4791518c4831bfa1fd335dc38464779c693dc2394f292d405fb912b"
)
CORRECTED_FRENCH_CALL_SHA256 = (
    "8f95b1fac7f59184bec6a6320a0196c7099aa2766d05efec0b0b273a567d1bcc"
)


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_known_bad_french_call(
    data_audio_dir: str | Path,
    bundled_audio_dir: str | Path,
    *,
    legacy_hash: str = LEGACY_FRENCH_CALL_SHA256,
    corrected_hash: str = CORRECTED_FRENCH_CALL_SHA256,
) -> str:
    """Replace only the exact legacy asset and preserve a recoverable backup."""

    data_audio_dir = Path(data_audio_dir)
    bundled_audio_dir = Path(bundled_audio_dir)
    target = data_audio_dir / "fr_call.mp3"
    corrected_source = bundled_audio_dir / "fr_call.mp3"
    backup = data_audio_dir / "fr_call.legacy-m4a.backup"
    temporary = data_audio_dir / "fr_call.mp3.migration.tmp"

    if not target.is_file():
        return "missing"
    if sha256_file(target) != legacy_hash.lower():
        return "unchanged"
    if not corrected_source.is_file():
        raise FileNotFoundError("No existe el audio francés corregido incluido en la imagen")
    if sha256_file(corrected_source) != corrected_hash.lower():
        raise ValueError("El audio francés corregido no coincide con la versión validada")

    data_audio_dir.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(target, backup)
    try:
        shutil.copy2(corrected_source, temporary)
        if sha256_file(temporary) != corrected_hash.lower():
            raise ValueError("La copia temporal del audio corregido no pasó la verificación")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "replaced"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Uso: audio_migrations.py <audios-persistentes> <audios-incluidos>", file=sys.stderr)
        return 2
    result = migrate_known_bad_french_call(argv[1], argv[2])
    print(f"Migración de audio francés: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
