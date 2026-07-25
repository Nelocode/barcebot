import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telethon.tl import types

from telegram_audio_branding import (
    AUDIO_PERFORMER,
    AUDIO_TITLE,
    brand_audio_attributes,
    build_branded_audio_media,
    resolve_audio_branding,
    resolve_audio_cover_path,
    save_audio_branding_settings,
)


class TelegramAudioBrandingTests(unittest.TestCase):
    def setUp(self):
        self.branding_environment = patch.dict(
            os.environ,
            {
                "TG_AUDIO_TITLE": "",
                "TG_AUDIO_PERFORMER": "",
                "TG_AUDIO_COVER_PATH": "",
            },
        )
        self.branding_environment.start()

    def tearDown(self):
        self.branding_environment.stop()

    def test_madrid_branding_remains_the_default(self):
        title, performer = resolve_audio_branding(environ={})

        self.assertEqual("Las Fiesteras", title)
        self.assertEqual("Caché Madrid", performer)

    def test_barcelona_branding_can_be_selected_per_deployment(self):
        with patch.dict(
            os.environ,
            {
                "TG_AUDIO_TITLE": "Las Fiesteras",
                "TG_AUDIO_PERFORMER": "Caché Barcelona",
            },
        ):
            branded = brand_audio_attributes([], filename="fr_msg1.mp3")

        audio = next(
            item for item in branded
            if isinstance(item, types.DocumentAttributeAudio)
        )
        self.assertEqual("Las Fiesteras", audio.title)
        self.assertEqual("Caché Barcelona", audio.performer)

    def test_packaged_barcelona_default_and_panel_override_have_clear_precedence(self):
        packaged = Path(__file__).parents[1] / "telegram_audio_branding.defaults.json"
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "telegram_audio_branding.json"
            with patch.dict(
                os.environ,
                {
                    "TG_AUDIO_TITLE": "Título de Easypanel",
                    "TG_AUDIO_PERFORMER": "Agencia de Easypanel",
                },
            ):
                title, performer = resolve_audio_branding(defaults_path=packaged)
                self.assertEqual("Título de Easypanel", title)
                self.assertEqual("Agencia de Easypanel", performer)

                save_audio_branding_settings(
                    settings,
                    performer="  Agencia elegida en el panel  ",
                )
                title, performer = resolve_audio_branding(
                    defaults_path=packaged,
                    settings_path=settings,
                )

        self.assertEqual("Título de Easypanel", title)
        self.assertEqual("Agencia elegida en el panel", performer)

    def test_packaged_default_is_barcelona_without_changing_builtin_madrid_fallback(self):
        packaged = Path(__file__).parents[1] / "telegram_audio_branding.defaults.json"

        self.assertEqual(
            ("Las Fiesteras", "Caché Barcelona"),
            resolve_audio_branding(environ={}, defaults_path=packaged),
        )
        self.assertEqual(
            ("Las Fiesteras", "Caché Madrid"),
            resolve_audio_branding(environ={}),
        )

    def test_invalid_panel_file_falls_back_without_blocking_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "telegram_audio_branding.json"
            settings.write_text("{not-json", encoding="utf-8")

            branded = brand_audio_attributes(
                [],
                filename="es_msg1.mp3",
                environ={"TG_AUDIO_PERFORMER": "Respaldo seguro"},
                settings_path=settings,
            )

        audio = next(
            item for item in branded
            if isinstance(item, types.DocumentAttributeAudio)
        )
        self.assertEqual("Respaldo seguro", audio.performer)

    def test_panel_setting_rejects_empty_long_and_control_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "telegram_audio_branding.json"
            for invalid in ("", "   ", "x" * 81, "Barcelona\nTG_API_HASH=injected"):
                with self.subTest(invalid=repr(invalid)):
                    with self.assertRaises(ValueError):
                        save_audio_branding_settings(settings, performer=invalid)
                    self.assertFalse(settings.exists())

    def test_panel_setting_is_written_as_utf8_json_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "telegram_audio_branding.json"

            saved = save_audio_branding_settings(
                settings,
                performer="Caché Barcelona",
            )

            self.assertEqual({"performer": "Caché Barcelona"}, saved)
            self.assertEqual(
                {"performer": "Caché Barcelona"},
                json.loads(settings.read_text(encoding="utf-8")),
            )
            self.assertFalse(settings.with_suffix(".json.tmp").exists())

    def test_brand_attributes_reloads_panel_setting_for_each_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "telegram_audio_branding.json"
            save_audio_branding_settings(settings, performer="Marca inicial")
            first = brand_audio_attributes(
                [],
                filename="es_msg1.mp3",
                environ={},
                settings_path=settings,
            )
            save_audio_branding_settings(settings, performer="Marca actualizada")
            second = brand_audio_attributes(
                [],
                filename="es_msg2.mp3",
                environ={},
                settings_path=settings,
            )

        first_audio = next(
            item for item in first if isinstance(item, types.DocumentAttributeAudio)
        )
        second_audio = next(
            item for item in second if isinstance(item, types.DocumentAttributeAudio)
        )
        self.assertEqual("Marca inicial", first_audio.performer)
        self.assertEqual("Marca actualizada", second_audio.performer)

    def test_blank_branding_variables_fall_back_to_madrid(self):
        with patch.dict(
            os.environ,
            {
                "TG_AUDIO_TITLE": "   ",
                "TG_AUDIO_PERFORMER": "   ",
            },
        ):
            title, performer = resolve_audio_branding()

        self.assertEqual(AUDIO_TITLE, title)
        self.assertEqual(AUDIO_PERFORMER, performer)

    def test_cover_path_is_isolated_per_deployment(self):
        base_dir = Path("/app")
        self.assertEqual(
            base_dir / "assets" / "audio-cover.jpg",
            resolve_audio_cover_path(base_dir, environ={}),
        )

        with patch.dict(
            os.environ,
            {"TG_AUDIO_COVER_PATH": "assets/audio-cover-barcelona.jpg"},
        ):
            self.assertEqual(
                base_dir / "assets" / "audio-cover-barcelona.jpg",
                resolve_audio_cover_path(base_dir),
            )

        with tempfile.TemporaryDirectory() as directory:
            absolute_cover = Path(directory) / "barcelona.jpg"
            with patch.dict(
                os.environ,
                {"TG_AUDIO_COVER_PATH": str(absolute_cover)},
            ):
                self.assertEqual(
                    absolute_cover,
                    resolve_audio_cover_path(base_dir),
                )

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
