import unittest
from pathlib import Path

from telethon.tl import types

from telegram_audio_branding import (
    AUDIO_PERFORMER,
    AUDIO_TITLE,
    brand_audio_attributes,
    build_branded_audio_media,
)


class TelegramAudioBrandingTests(unittest.TestCase):
    def test_preserves_duration_and_filename_while_enforcing_brand(self):
        attributes = [
            types.DocumentAttributeFilename(file_name="es_msg2.mp3"),
            types.DocumentAttributeAudio(
                duration=21,
                voice=True,
                title="old",
                performer="old",
            ),
        ]

        branded = brand_audio_attributes(attributes, filename="ignored.mp3")

        filename = next(
            item for item in branded
            if isinstance(item, types.DocumentAttributeFilename)
        )
        audio = next(
            item for item in branded
            if isinstance(item, types.DocumentAttributeAudio)
        )
        self.assertEqual("es_msg2.mp3", filename.file_name)
        self.assertEqual(21, audio.duration)
        self.assertFalse(audio.voice)
        self.assertEqual(AUDIO_TITLE, audio.title)
        self.assertEqual(AUDIO_PERFORMER, audio.performer)

    def test_adds_filename_and_zero_duration_when_probe_has_no_audio_metadata(self):
        branded = brand_audio_attributes([], filename="fr_call.mp3")

        self.assertTrue(any(
            isinstance(item, types.DocumentAttributeFilename)
            and item.file_name == "fr_call.mp3"
            for item in branded
        ))
        audio = next(
            item for item in branded
            if isinstance(item, types.DocumentAttributeAudio)
        )
        self.assertEqual(0, audio.duration)
        self.assertFalse(audio.voice)

    def test_media_payload_contains_cover_without_becoming_a_document(self):
        audio_file = types.InputFile(
            id=1,
            parts=1,
            name="es_msg2.mp3",
            md5_checksum="",
        )
        cover_file = types.InputFile(
            id=2,
            parts=1,
            name="audio-cover.jpg",
            md5_checksum="",
        )
        attributes = brand_audio_attributes([], filename="es_msg2.mp3")

        media = build_branded_audio_media(
            uploaded_file=audio_file,
            uploaded_thumb=cover_file,
            mime_type="audio/mpeg",
            attributes=attributes,
        )

        self.assertIs(audio_file, media.file)
        self.assertIs(cover_file, media.thumb)
        self.assertEqual("audio/mpeg", media.mime_type)
        self.assertFalse(media.force_file)

    def test_packaged_cover_is_a_small_jpeg(self):
        cover = Path(__file__).parents[1] / "assets" / "audio-cover.jpg"
        payload = cover.read_bytes()

        self.assertLessEqual(len(payload), 20_000)
        self.assertTrue(payload.startswith(b"\xff\xd8"))
        self.assertTrue(payload.endswith(b"\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
