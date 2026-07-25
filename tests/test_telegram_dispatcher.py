import asyncio
from pathlib import Path
import tempfile
import unittest

from telethon.tl import functions, types

from interaction_state import PersistentInteractionState
from telegram_dispatcher import (
    TelegramInteractionDispatcher,
    build_telegram_media_request,
    build_telegram_text_request,
    telegram_delivery_random_id,
)


class TelegramInteractionDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_chat_delivers_step1_completely_before_step2(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentInteractionState(Path(directory) / "state.json")
            order = []
            first_started = asyncio.Event()
            release_first = asyncio.Event()

            async def send_response(_chat_id, response_key, _language, _fingerprint):
                order.append(f"{response_key}:start")
                if response_key == "step1":
                    first_started.set()
                    await release_first.wait()
                order.append(f"{response_key}:end")

            dispatcher = TelegramInteractionDispatcher(state, send_response)
            first = asyncio.create_task(dispatcher.dispatch(
                chat_id=1,
                event_id="message:1",
                kind="content",
            ))
            await first_started.wait()
            second = asyncio.create_task(dispatcher.dispatch(
                chat_id=1,
                event_id="message:2",
                kind="content",
            ))
            await asyncio.sleep(0)

            self.assertEqual(["step1:start"], order)
            release_first.set()
            await asyncio.gather(first, second)
            self.assertEqual(
                ["step1:start", "step1:end", "step2:start", "step2:end"],
                order,
            )

    async def test_duplicate_does_not_send_a_second_response(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentInteractionState(Path(directory) / "state.json")
            deliveries = []

            async def send_response(*args):
                deliveries.append(args)

            dispatcher = TelegramInteractionDispatcher(state, send_response)
            await dispatcher.dispatch(chat_id=1, event_id="call:1", kind="call")
            duplicate = await dispatcher.dispatch(chat_id=1, event_id="call:1", kind="call")

            self.assertTrue(duplicate.duplicate)
            self.assertEqual(1, len(deliveries))

    async def test_every_distinct_call_uses_call_even_after_prior_interactions(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentInteractionState(Path(directory) / "state.json")
            deliveries = []

            async def send_response(_peer, response_key, _language, _fingerprint):
                deliveries.append(response_key)

            dispatcher = TelegramInteractionDispatcher(state, send_response)
            await dispatcher.dispatch(
                chat_id=1,
                event_id="message:1",
                kind="content",
            )
            first_call = await dispatcher.dispatch(
                chat_id=1,
                event_id="call:700",
                kind="call",
            )
            second_call = await dispatcher.dispatch(
                chat_id=1,
                event_id="call:701",
                kind="call",
            )
            duplicate_fallback = await dispatcher.dispatch(
                chat_id=1,
                event_id="call:701",
                kind="call",
            )
            following_content = await dispatcher.dispatch(
                chat_id=1,
                event_id="message:2",
                kind="content",
            )

            self.assertEqual("call", first_call.response_key)
            self.assertEqual("call", second_call.response_key)
            self.assertTrue(duplicate_fallback.duplicate)
            self.assertEqual("step2", following_content.response_key)
            self.assertEqual(["step1", "call", "call", "step2"], deliveries)

    async def test_failed_delivery_does_not_consume_call_and_fallback_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = PersistentInteractionState(state_path)
            attempts = []

            async def send_response(peer, response_key, _language, fingerprint):
                attempts.append((peer, response_key, fingerprint))
                if len(attempts) == 1:
                    raise RuntimeError("delivery failed")

            dispatcher = TelegramInteractionDispatcher(state, send_response)
            with self.assertRaises(RuntimeError):
                await dispatcher.dispatch(
                    chat_id=1,
                    event_id="call:77",
                    kind="call",
                    reply_peer="input-peer",
                )

            pending_after_reload = PersistentInteractionState(state_path).preview(
                contact_id=1,
                event_id="call:77",
                kind="call",
            )
            self.assertFalse(pending_after_reload.duplicate)
            self.assertEqual("call", pending_after_reload.response_key)

            recovered = await dispatcher.dispatch(
                chat_id=1,
                event_id="call:77",
                kind="call",
                reply_peer="input-peer",
            )
            duplicate = await dispatcher.dispatch(
                chat_id=1,
                event_id="call:77",
                kind="call",
                reply_peer="input-peer",
            )

            self.assertEqual("call", recovered.response_key)
            self.assertTrue(duplicate.duplicate)
            duplicate_after_reload = PersistentInteractionState(state_path).preview(
                contact_id=1,
                event_id="call:77",
                kind="call",
            )
            self.assertTrue(duplicate_after_reload.duplicate)
            self.assertEqual(2, len(attempts))
            self.assertEqual(attempts[0], attempts[1])
            fingerprint = attempts[0][2]
            self.assertEqual(64, len(fingerprint))
            self.assertNotIn("call:77", fingerprint)
            self.assertNotEqual("1", fingerprint)
            self.assertEqual(
                telegram_delivery_random_id(fingerprint, "text"),
                telegram_delivery_random_id(attempts[1][2], "text"),
            )

            primary_request = build_telegram_text_request(
                types.InputPeerSelf(),
                "respuesta",
                attempts[0][2],
            )
            retry_request = build_telegram_text_request(
                types.InputPeerSelf(),
                "respuesta",
                attempts[0][2],
            )
            fallback_request = build_telegram_text_request(
                types.InputPeerSelf(),
                "respuesta",
                attempts[1][2],
            )
            self.assertIsInstance(primary_request, functions.messages.SendMessageRequest)
            self.assertEqual(
                primary_request.random_id,
                retry_request.random_id,
            )
            self.assertEqual(
                primary_request.random_id,
                fallback_request.random_id,
            )

    async def test_delivery_ids_are_stable_per_component_and_distinct_between_components(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentInteractionState(Path(directory) / "state.json")
            fingerprints = []

            async def send_response(_peer, _response_key, _language, fingerprint):
                fingerprints.append(fingerprint)

            dispatcher = TelegramInteractionDispatcher(state, send_response)
            await dispatcher.dispatch(
                chat_id=451,
                event_id="message:9001",
                kind="content",
            )

            fingerprint = fingerprints[0]
            text_id = telegram_delivery_random_id(fingerprint, "text")
            audio_id = telegram_delivery_random_id(fingerprint, "audio")
            self.assertEqual(text_id, telegram_delivery_random_id(fingerprint, "text"))
            self.assertNotEqual(text_id, audio_id)
            self.assertGreaterEqual(text_id, -(2**63))
            self.assertLessEqual(text_id, 2**63 - 1)
            self.assertGreaterEqual(audio_id, -(2**63))
            self.assertLessEqual(audio_id, 2**63 - 1)

            text_request = build_telegram_text_request(
                types.InputPeerSelf(),
                "respuesta",
                fingerprint,
            )
            audio_request = build_telegram_media_request(
                types.InputPeerSelf(),
                types.InputMediaEmpty(),
                fingerprint,
            )
            self.assertIsInstance(text_request, functions.messages.SendMessageRequest)
            self.assertIsInstance(audio_request, functions.messages.SendMediaRequest)
            self.assertEqual(text_id, text_request.random_id)
            self.assertEqual(audio_id, audio_request.random_id)


if __name__ == "__main__":
    unittest.main()
