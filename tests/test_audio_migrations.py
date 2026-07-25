import hashlib
from pathlib import Path
import tempfile
import unittest

from audio_migrations import migrate_known_bad_french_call


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class AudioMigrationTests(unittest.TestCase):
    def test_replaces_only_exact_legacy_file_and_keeps_backup(self):
        legacy = b"legacy-m4a-container"
        corrected = b"corrected-real-mp3"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            bundled_dir = root / "bundled"
            data_dir.mkdir()
            bundled_dir.mkdir()
            (data_dir / "fr_call.mp3").write_bytes(legacy)
            (bundled_dir / "fr_call.mp3").write_bytes(corrected)

            result = migrate_known_bad_french_call(
                data_dir,
                bundled_dir,
                legacy_hash=digest(legacy),
                corrected_hash=digest(corrected),
            )

            self.assertEqual("replaced", result)
            self.assertEqual(corrected, (data_dir / "fr_call.mp3").read_bytes())
            self.assertEqual(legacy, (data_dir / "fr_call.legacy-m4a.backup").read_bytes())

    def test_preserves_personalized_file_using_the_same_name(self):
        legacy = b"legacy-m4a-container"
        personalized = b"client-personalized-audio"
        corrected = b"corrected-real-mp3"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            bundled_dir = root / "bundled"
            data_dir.mkdir()
            bundled_dir.mkdir()
            (data_dir / "fr_call.mp3").write_bytes(personalized)
            (bundled_dir / "fr_call.mp3").write_bytes(corrected)

            result = migrate_known_bad_french_call(
                data_dir,
                bundled_dir,
                legacy_hash=digest(legacy),
                corrected_hash=digest(corrected),
            )

            self.assertEqual("unchanged", result)
            self.assertEqual(personalized, (data_dir / "fr_call.mp3").read_bytes())
            self.assertFalse((data_dir / "fr_call.legacy-m4a.backup").exists())

    def test_refuses_an_unvalidated_bundled_replacement(self):
        legacy = b"legacy-m4a-container"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            bundled_dir = root / "bundled"
            data_dir.mkdir()
            bundled_dir.mkdir()
            (data_dir / "fr_call.mp3").write_bytes(legacy)
            (bundled_dir / "fr_call.mp3").write_bytes(b"unexpected")

            with self.assertRaises(ValueError):
                migrate_known_bad_french_call(
                    data_dir,
                    bundled_dir,
                    legacy_hash=digest(legacy),
                    corrected_hash=digest(b"expected"),
                )
            self.assertEqual(legacy, (data_dir / "fr_call.mp3").read_bytes())


if __name__ == "__main__":
    unittest.main()
