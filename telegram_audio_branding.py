"""Small, deterministic helpers for branded Telegram audio messages."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from telethon.tl import types

try:
    from hachoir.core import config as hachoir_config
except ImportError:  # Optional locally; installed in the production image.
    hachoir_config = None
else:
    # Some generated MP3s contain large C2PA/GEOB records. Their warnings do
    # not affect duration extraction and would otherwise flood worker logs.
    hachoir_config.quiet = True


AUDIO_TITLE = "Las Fiesteras"
AUDIO_PERFORMER = "Caché Madrid"


def _environment_text(
    environ: Mapping[str, str],
    name: str,
    default: str,
) -> str:
    value = environ.get(name, "")
    if not isinstance(value, str):
        return default
    return value.strip() or default


def resolve_audio_branding(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve per-deployment labels while preserving Madrid defaults."""

    source = os.environ if environ is None else environ
    return (
        _environment_text(source, "TG_AUDIO_TITLE", AUDIO_TITLE),
        _environment_text(source, "TG_AUDIO_PERFORMER", AUDIO_PERFORMER),
    )


def resolve_audio_cover_path(
    base_dir: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve a deployment-specific cover relative to the application root."""

    source = os.environ if environ is None else environ
    application_root = Path(base_dir)
    configured = _environment_text(source, "TG_AUDIO_COVER_PATH", "")
    if not configured:
        return application_root / "assets" / "audio-cover.jpg"

    candidate = Path(configured).expanduser()
    if candidate.is_absolute():
        return candidate
    return application_root / candidate


def brand_audio_attributes(
    attributes: Iterable[object],
    *,
    filename: str,
) -> list[object]:
    """Preserve file metadata and enforce Telegram's non-voice audio card."""

    title, performer = resolve_audio_branding()
    result: list[object] = []
    duration = 0
    has_filename = False

    for attribute in attributes:
        if isinstance(attribute, types.DocumentAttributeAudio):
            try:
                duration = max(0, int(attribute.duration or 0))
            except (TypeError, ValueError):
                duration = 0
            continue
        if isinstance(attribute, types.DocumentAttributeFilename):
            has_filename = True
        result.append(attribute)

    if not has_filename:
        result.append(types.DocumentAttributeFilename(file_name=filename))
    result.append(
        types.DocumentAttributeAudio(
            duration=duration,
            voice=False,
            title=title,
            performer=performer,
        )
    )
    return result


def build_branded_audio_media(
    *,
    uploaded_file: object,
    uploaded_thumb: object | None,
    mime_type: str,
    attributes: list[object],
):
    """Create Telegram's audio media payload with an optional cover image."""

    return types.InputMediaUploadedDocument(
        file=uploaded_file,
        thumb=uploaded_thumb,
        mime_type=mime_type,
        attributes=attributes,
        force_file=False,
    )
