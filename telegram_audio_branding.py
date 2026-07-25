"""Small, deterministic helpers for branded Telegram audio messages."""

from __future__ import annotations

from collections.abc import Iterable

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


def brand_audio_attributes(
    attributes: Iterable[object],
    *,
    filename: str,
) -> list[object]:
    """Preserve file metadata and enforce Telegram's non-voice audio card."""

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
            title=AUDIO_TITLE,
            performer=AUDIO_PERFORMER,
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
