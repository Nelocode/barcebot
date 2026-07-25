import asyncio
from pathlib import Path
import tempfile
import unittest

from interaction_state import PersistentInteractionState
from telegram_dispatcher import TelegramInteractionDispatcher


class TelegramInteractionDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_chat_delivers_step1_completely_before_step2(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentInteractionState(Path(directory) / "state.json")
            order = []
            first_started = asyncio.Event()
            release_first = asyncio.Event()

            async def send_response(_chat_id, response_key, _language):
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


if __name__ == "__main__":
    unittest.main()
