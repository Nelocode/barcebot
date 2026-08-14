from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.modules.setdefault("telegram", SimpleNamespace(Update=object))
sys.modules.setdefault(
    "telegram.ext",
    SimpleNamespace(
        Application=object,
        CommandHandler=object,
        MessageHandler=object,
        filters=SimpleNamespace(),
        ContextTypes=SimpleNamespace(DEFAULT_TYPE=object),
    ),
)

import botfather_bot


class BotFatherProvisionalLanguageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        botfather_bot.user_state.clear()
        self.messages = {
            language: {
                "steps": [
                    (f"{language}-step1", "", False),
                    (f"{language}-step2", "", False),
                ],
                "call": {"text": f"{language}-call", "audio": ""},
            }
            for language in ("es", "en", "fr")
        }

    @staticmethod
    def update(*, text=None, caption=None, chat_id=7, voice=None, video_note=None):
        message = SimpleNamespace(
            text=text,
            caption=caption,
            voice=voice,
            video_note=video_note,
            reply_text=AsyncMock(),
            reply_audio=AsyncMock(),
        )
        return SimpleNamespace(
            effective_chat=SimpleNamespace(id=chat_id),
            message=message,
        )

    async def test_image_without_caption_is_spanish_provisional_then_english_text_wins(self):
        image = self.update(caption="photo")
        english = self.update(text="I need help", chat_id=7)
        with patch.object(botfather_bot, "MESSAGES", self.messages), patch.object(
            botfather_bot, "load_messages_fresh"
        ):
            await botfather_bot.handle_message(image, None)
            await botfather_bot.handle_message(english, None)

        image.message.reply_text.assert_awaited_once_with("es-step1")
        english.message.reply_text.assert_awaited_once_with("en-step2")
        self.assertEqual("en", botfather_bot.user_state[7]["lang"])
        self.assertFalse(botfather_bot.user_state[7]["language_provisional"])

    async def test_video_note_without_caption_creates_spanish_provisional_state(self):
        call = self.update(chat_id=8, video_note=object())
        with patch.object(botfather_bot, "MESSAGES", self.messages):
            await botfather_bot.handle_call(call, None)

        call.message.reply_text.assert_awaited_once_with("es-call")
        self.assertEqual("es", botfather_bot.user_state[8]["lang"])
        self.assertTrue(botfather_bot.user_state[8]["language_provisional"])

    async def test_voice_with_english_caption_uses_english_immediately(self):
        call = self.update(chat_id=9, caption="Are you available now", voice=object())
        with patch.object(botfather_bot, "MESSAGES", self.messages):
            await botfather_bot.handle_call(call, None)

        call.message.reply_text.assert_awaited_once_with("en-call")
        self.assertEqual("en", botfather_bot.user_state[9]["lang"])
        self.assertFalse(botfather_bot.user_state[9]["language_provisional"])

    def test_ambiguous_text_stays_provisional_but_english_evidence_is_detected(self):
        self.assertIsNone(botfather_bot.detect_lang("ok"))
        self.assertEqual("en", botfather_bot.detect_lang("hello"))
        self.assertEqual("en", botfather_bot.detect_lang("Are you available now"))
        self.assertEqual("en", botfather_bot.detect_lang("I need help"))
        self.assertIsNone(botfather_bot.detect_lang("photo"))
        self.assertIsNone(botfather_bot.detect_lang("video"))

    def test_weak_language_needs_two_consecutive_messages_after_provisional(self):
        state, _ = botfather_bot.update_user_language(None, None, now=100)
        first, _ = botfather_bot.update_user_language(
            state,
            None,
            now=101,
            language_evidence={
                "language": "en",
                "strong": False,
                "explicit": False,
                "score": 4,
                "margin": 4,
            },
        )
        self.assertEqual("es", first["lang"])
        self.assertEqual("en", first["language_candidate"])
        second, _ = botfather_bot.update_user_language(
            first,
            None,
            now=102,
            language_evidence={
                "language": "en",
                "strong": False,
                "explicit": False,
                "score": 4,
                "margin": 4,
            },
        )

        self.assertEqual("en", second["lang"])
        self.assertFalse(second["language_provisional"])

    def test_strong_evidence_overrides_operator_seed_and_clears_candidate(self):
        seeded = {
            "lang": "fr",
            "language_provisional": False,
            "language_source": "operator_seed",
            "language_candidate": "en",
            "language_candidate_streak": 1,
            "step": 0,
            "last_seen": 100,
        }
        updated, _ = botfather_bot.update_user_language(
            seeded,
            None,
            now=101,
            language_evidence={
                "language": "es",
                "strong": True,
                "explicit": False,
                "score": 11,
                "margin": 11,
            },
        )

        self.assertEqual("es", updated["lang"])
        self.assertEqual("detected", updated["language_source"])
        self.assertIsNone(updated["language_candidate"])


if __name__ == "__main__":
    unittest.main()
